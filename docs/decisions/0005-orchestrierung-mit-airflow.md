# 0005 – Orchestrierung mit Airflow

Status: angenommen · 2026-10-26

## Kontext
Die Pipeline soll täglich laufen, nachladbar sein, Fehler und Verspätung melden und auf einem
Laptop mit 8 GB RAM laufen.

## Entscheidung
- **Airflow 3.3.2** (aktuelle stabile Version) mit **LocalExecutor**. Die offizielle
  Compose-Datei nutzt Celery mit Redis und Workern; das braucht für einen DAG deutlich mehr
  Speicher, ohne Nutzen. Dienste: `api-server`, `scheduler` (die Tasks laufen in diesem Container),
  `dag-processor`. Kein Triggerer, weil nichts asynchron wartet.
- **Eigenes Image:** Das Paket `power_market` wird mit der offiziellen Constraints-Datei
  installiert, dbt läuft in einem eigenen virtualenv, damit sich die Abhängigkeiten nicht
  gegenseitig festlegen. Die Untergrenzen in `pyproject.toml` sind deshalb großzügig
  (`boto3>=1.34` statt der neuesten Version), die genauen Entwicklungsversionen stehen in `uv.lock`.
- **Zeitplan:** `CronDataIntervalTimetable("0 6 * * *", UTC)` mit echten Tagesintervallen. 06:00 UTC,
  weil SMARD bis dahin den Vortag größtenteils veröffentlicht hat.
- **Aufbau:** Eine gemappte Task pro SMARD-Reihe (14) und pro Wetterort (6), höchstens drei
  gleichzeitig. Danach `dbt source freshness` und `dbt build` auf dem prod-Ziel, beides mit
  `all_success`: Fehlt eine Quelle, laufen die Modelle nicht auf halben Daten, und der DAG-Lauf ist
  sichtbar rot.
- **Zeiträume:** Geplante Läufe arbeiten inkrementell mit der Watermark. Backfill-Läufe
  (`airflow backfill create`) laden ihr Intervall, manuelle Läufe können `window_start` und
  `window_end` setzen. Die Run-ID ist ein `uuid5` aus DAG-Run-ID, damit ein wiederholter Lauf seine
  Zeilen im Lauf-Protokoll überschreibt.
- **Fehler und Verspätung:** 3 Wiederholungen mit wachsendem Abstand; danach Task- bzw.
  DAG-Alarm über Slack-Webhook oder nur Log. `dagrun_timeout` von zwei Stunden lässt einen zu langen
  Lauf fehlschlagen und löst damit denselben Alarm aus. Die „Deadline Alerts“ von Airflow 3 sind
  in 3.3 noch experimentell und hier nicht nötig.
- **Test:** Ein Skript prüft im gebauten Image, dass der DAG ohne Fehler importiert und die
  erwartete Struktur hat (CI-Job `airflow`).

## Folgen
- `make up` baut das Image und startet alles, der DAG ist nicht pausiert und startet sofort.
- Simple Auth Manager mit einem Admin-Benutzer: gut für lokal, nicht für einen Produktivbetrieb.
