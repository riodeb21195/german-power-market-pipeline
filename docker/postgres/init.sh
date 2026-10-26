#!/bin/sh
# Runs once on an empty data volume: one role and database per component.
set -eu

create_db() {
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
    -v db="$1" -v usr="$2" -v pw="$3" <<'SQL'
select format('create role %I login password %L', :'usr', :'pw') \gexec
select format('create database %I owner %I', :'db', :'usr') \gexec
SQL
}

create_db "$WAREHOUSE_DB" "$WAREHOUSE_USER" "$WAREHOUSE_PASSWORD"
