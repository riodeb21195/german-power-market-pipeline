# Setup und Befehle

Kurzfassung: [README](../README.md#quickstart). Hilfe bei Fehlern: [runbook.md](runbook.md).

## Voraussetzungen und Start

Docker (≥ 6 GB RAM für Docker), [uv](https://docs.astral.sh/uv/), make.

```bash
git clone https://github.com/riodeb21195/german-power-market-pipeline.git
cd german-power-market-pipeline
make install
cp .env.example .env    # alle change-me ersetzen, der Befehl für den Fernet-Key steht in der Datei
make up                 # Postgres, Silo, Airflow; der DAG startet sofort
make up PROFILES=bi     # zusätzlich Metabase auf http://localhost:3000
```

Airflow: http://localhost:8080, Benutzer `admin`, Passwort `AIRFLOW_ADMIN_PASSWORD` aus `.env`.

## Messumgebung der Kennzahlen

Gemessen am 26.10.2026 auf einem Intel-MacBook (2019, 8 GB RAM), Start mit leeren Volumes.

- `make up` bis fertig geladene Daten: ca. 12 Minuten; der erste DAG-Lauf (Daten ab 01.01.2023 + dbt) dauerte 589 s.
- Daten: 647.441 Zeilen aus 20 Quellen: 446.561 Strommarkt-, 200.880 Wetterzeilen, 33.431 vollständige Stunden.
- Speicher: ca. 2,7 GB mit allen Diensten inkl. Metabase.

## Dashboard einrichten

Nach `make up PROFILES=bi` auf http://localhost:3000 ein Konto anlegen und die Datenbank
hinzufügen: Postgres, Host `postgres`, Port `5432`, Datenbank und Benutzer aus `.env`, Schema
`analytics_marts`. Dann für jede Datei in `metabase/questions/` eine SQL-Frage anlegen.

## Befehle

| | |
|---|---|
| `make up` / `make down` | Stack starten / stoppen |
| `make test` / `make lint` / `make format` | Tests / Prüfung / Formatierung |
| `make run` / `make backfill START=… END=…` | Lauf bzw. Zeitraum über die Kommandozeile |
| `make dbt-build` / `make dbt-docs` | dbt bauen / Data Dictionary |
| `make dag-check` | Airflow-Image bauen und DAG prüfen |

## Projektstruktur

```
airflow/            Dockerfile, DAG, DAG-Prüfung
dbt/                staging, intermediate, marts, seeds, tests
docker/postgres/    Datenbanken beim ersten Start
metabase/questions/ SQL der Dashboard-Fragen
src/power_market/   Extract, Load, Pipeline, CLI, Alerting
tests/              Unit, Integration, aufgezeichnete API-Antworten
docs/               Architektur, Entscheidungen, Setup, Runbook, Screenshot
```
