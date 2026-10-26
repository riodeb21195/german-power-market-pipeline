"""Command line entry point: `python -m power_market run|backfill`."""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from collections.abc import Sequence
from datetime import date

from power_market.alerting import Alert, send_alert
from power_market.config import get_settings
from power_market.log import configure_logging
from power_market.pipeline import backfill_window, build_pipeline
from power_market.smard import SMARD_SERIES
from power_market.weather import LOCATIONS

SERIES_BY_SLUG = {s.slug: s for s in SMARD_SERIES}
LOCATIONS_BY_SLUG = {loc.slug: loc for loc in LOCATIONS}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="power_market", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--source",
        choices=["all", "smard", "weather"],
        default="all",
        help="restrict to one source family",
    )
    common.add_argument(
        "--only",
        nargs="+",
        metavar="SLUG",
        choices=sorted(SERIES_BY_SLUG | LOCATIONS_BY_SLUG),
        help="restrict to specific SMARD series or weather locations",
    )
    common.add_argument("--run-id", type=uuid.UUID, help="reuse a run id (e.g. for retries)")
    common.add_argument("--orchestrator-run-id", help="e.g. the Airflow dag_run id")

    sub.add_parser("run", parents=[common], help="incremental run from the watermarks")
    backfill = sub.add_parser("backfill", parents=[common], help="(re)load a fixed date range")
    backfill.add_argument("--start", type=date.fromisoformat, required=True)
    backfill.add_argument(
        "--end", type=date.fromisoformat, default=None, help="inclusive, default today"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level)

    only = set(args.only or [])
    series = tuple(
        s for s in SMARD_SERIES if args.source in {"all", "smard"} and (not only or s.slug in only)
    )
    locations = tuple(
        loc
        for loc in LOCATIONS
        if args.source in {"all", "weather"} and (not only or loc.slug in only)
    )
    window = None
    if args.command == "backfill":
        end = args.end or date.today()  # noqa: DTZ011 - a calendar date is meant here
        if end < args.start:
            print("--end must not be before --start", file=sys.stderr)
            return 2
        window = backfill_window(args.start, end)

    with build_pipeline(settings) as pipeline:
        results = pipeline.run_all(
            run_id=args.run_id,
            window=window,
            series=series,
            locations=locations,
            orchestrator_run_id=args.orchestrator_run_id,
        )

    failed = [r for r in results if r.status == "failed"]
    summary = {
        "command": args.command,
        "sources": len(results),
        "failed": len(failed),
        "rows_extracted": sum(r.stats.rows_extracted for r in results),
        "rows_inserted": sum(r.stats.rows_inserted for r in results),
        "rows_updated": sum(r.stats.rows_updated for r in results),
        "results": [r.as_dict() for r in results],
    }
    print(json.dumps(summary, indent=2))
    if failed:
        details = "\n".join(f"{r.source}: {r.error}" for r in failed)
        title = f"power_market {args.command}: {len(failed)} of {len(results)} sources failed"
        send_alert(Alert(title=title, message=details), settings)
    return 1 if failed else 0
