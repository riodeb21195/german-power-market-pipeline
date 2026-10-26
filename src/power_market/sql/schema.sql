-- Warehouse objects owned by the Python loader. Idempotent: safe to run on every pipeline start.
-- dbt owns everything downstream of the `raw` schema.

create schema if not exists raw;
create schema if not exists meta;

-- ---------------------------------------------------------------------------
-- raw: one row per natural key, latest version wins (MERGE upsert)
-- ---------------------------------------------------------------------------
create table if not exists raw.smard_timeseries (
    filter_id integer not null,
    region text not null,
    ts timestamptz not null,
    value double precision not null,
    chunk_start timestamptz not null,
    landing_key text not null,
    run_id uuid not null,
    loaded_at timestamptz not null default now(),
    primary key (filter_id, region, ts)
);

create table if not exists raw.weather_hourly (
    location text not null,
    ts timestamptz not null,
    temperature_2m double precision,
    wind_speed_100m double precision,
    shortwave_radiation double precision,
    cloud_cover double precision,
    landing_key text not null,
    run_id uuid not null,
    loaded_at timestamptz not null default now(),
    primary key (location, ts)
);

-- ---------------------------------------------------------------------------
-- meta: pipeline state and observability
-- ---------------------------------------------------------------------------
create table if not exists meta.checkpoints (
    source text primary key,
    watermark timestamptz not null,
    last_run_id uuid not null,
    updated_at timestamptz not null default now()
);

create table if not exists meta.pipeline_runs (
    run_id uuid not null,
    source text not null,
    mode text not null check (mode in ('incremental', 'backfill')),
    window_start timestamptz not null,
    window_end timestamptz not null,
    status text not null check (status in ('running', 'success', 'failed')),
    rows_extracted integer,
    rows_inserted integer,
    rows_updated integer,
    rows_unchanged integer,
    error text,
    orchestrator_run_id text,
    started_at timestamptz not null default now(),
    finished_at timestamptz,
    primary key (run_id, source)
);

create table if not exists meta.reconciliation (
    run_id uuid not null,
    source text not null,
    window_start timestamptz not null,
    window_end timestamptz not null,
    source_rows integer not null,
    target_rows integer not null,
    status text not null check (status in ('match', 'mismatch')),
    checked_at timestamptz not null default now(),
    primary key (run_id, source)
);
