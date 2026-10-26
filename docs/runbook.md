# Runbook

Was tun, wenn etwas schiefgeht. Die Befehle laufen im Projektordner bei laufendem Stack.

```bash
# letzte Läufe je Quelle
docker compose exec postgres psql -U postgres -d warehouse -c \
  "select source, mode, status, rows_extracted, rows_inserted, rows_updated, error, started_at
   from meta.pipeline_runs order by started_at desc limit 20;"

# Abgleich und Watermarks
docker compose exec postgres psql -U postgres -d warehouse -c "select * from meta.reconciliation order by checked_at desc limit 20;"
docker compose exec postgres psql -U postgres -d warehouse -c "select * from meta.checkpoints order by source;"
```

Task-Logs: Airflow-Oberfläche (http://localhost:8080) → `power_market_daily` → Lauf → Task → Logs.

## Alarm „Task failed“ mit `HTTP 5xx`, `429` oder `ReadTimeout`
Die Quelle war über alle Wiederholungen nicht erreichbar. Für diese Quelle wurde nichts geschrieben,
die anderen sind unberührt.
1. Quelle prüfen: `curl -I https://www.smard.de/app/chart_data/4169/DE-LU/index_hour.json`
2. Ist sie wieder da: den Task in Airflow mit „Clear“ neu starten. Sonst wartet man einfach auf den
   nächsten Lauf, der ab Watermark minus Rückblick lädt.
3. Bei `429`: `HTTP_RATE_LIMIT_PER_SECOND` in `.env` senken und `make up`.

## Alarm mit `SchemaDriftError`
Die Antwort der Quelle hat ein anderes Format. Es wurde nichts gespeichert.
1. Die genannten Abweichungen lesen (`unexpected field …`, `missing field …`, `hourly_units changed …`).
2. Eine aktuelle Antwort holen und mit der aufgezeichneten unter `tests/fixtures/` vergleichen.
3. Ist die Änderung harmlos: Modell in `src/power_market/schemas.py` und Fixture anpassen, Tests
   ausführen, committen. Hat sich die Bedeutung geändert (z. B. Einheit), auch das Staging in dbt.

## Alarm mit `ReconciliationError`
Nach dem Laden stimmt die Zahl der Stunden in der Datenbank nicht mit der Quelle überein.
- Ziel hat mehr Zeilen: Die Quelle hat Werte zurückgezogen. Die betroffenen Stunden prüfen und
  gegebenenfalls aus `raw.smard_timeseries` löschen, dann den Task neu starten.
- Ziel hat weniger Zeilen: Task neu starten; bleibt es, die Postgres-Logs prüfen.

## Alarm „DAG run failed“ wegen Timeout
Der Lauf hat länger als zwei Stunden gedauert. Meist ist eine Quelle sehr langsam oder dem
Scheduler fehlt Speicher (`docker stats`, Limit 1,5 GB). Metabase stoppen
(`docker compose stop metabase`) entlastet.

## `dbt_source_freshness` oder `dbt_build` schlägt fehl
- Freshness: seit 54 Stunden keine neuen Daten. Prüfen, ob SMARD die Daten selbst noch nicht hat.
- Preis außerhalb der Grenzen: Die SDAC-Preisgrenzen wurden geändert. Variablen
  `price_floor_eur_mwh` / `price_cap_eur_mwh` in `dbt/dbt_project.yml` anpassen.
- `assert_complete_days_have_all_local_hours`: Lücke in den Rohdaten. Den Tag nachladen.
- Lokal nachvollziehen: `make dbt-build`.

## Zeitraum nachladen
```bash
make backfill START=2025-01-01 END=2025-01-31
docker compose exec airflow-scheduler airflow backfill create \
  --dag-id power_market_daily --from-date 2025-01-01 --to-date 2025-01-31
```
Danach `dbt build` laufen lassen (nächster DAG-Lauf oder `make dbt-build TARGET=prod`).

## Alles zurücksetzen
`docker compose --profile bi down -v` löscht alle Daten. Danach `make up`: Der erste Lauf lädt
wieder alles ab `BACKFILL_START_DATE`.
