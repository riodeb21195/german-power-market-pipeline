# Designentscheidungen, Fehlerszenarien und Grenzen

Ausführliche Begründungen als ADRs: [decisions/](decisions/). Hilfe bei Fehlern: [runbook.md](runbook.md).

## What happens when …

| Fall | Verhalten | Belegt durch |
|---|---|---|
| die Quelle mit 5xx antwortet oder hängt | Retry mit Backoff, danach Lauf `failed`, nichts gespeichert, Slack- bzw. Log-Alarm | `tests/unit/test_http.py`, `tests/integration/test_pipeline.py` |
| sich das Format ändert | `SchemaDriftError … unexpected field 'unit'`, kein Retry, nichts gespeichert, andere Quellen laufen weiter | `tests/unit/test_schemas.py`, `tests/integration/test_pipeline.py` |
| ein Lauf doppelt ausgeführt wird | 0 eingefügt, 0 aktualisiert, keine neue Rohdatei | `tests/integration/test_pipeline.py`, `test_warehouse.py` |
| SMARD alte Werte korrigiert | der 7-Tage-Rückblick liest sie erneut, nur geänderte Zeilen werden aktualisiert | `tests/integration/test_pipeline.py` |
| ein Lauf zu lange dauert | `dagrun_timeout` (2 h) lässt ihn fehlschlagen, das löst den DAG-Alarm aus | `airflow/tests/check_dags.py` |
| keine neuen Daten kommen | `dbt source freshness` warnt nach 30 h, bricht nach 54 h ab | `dbt/models/staging/_sources.yml` |

Beim Laden über die Kommandozeile brach einmal eine SMARD-Verbindung ab (`RemoteProtocolError`),
der Retry hat es abgefangen.

## Bewusst weggelassen

- **SCD Typ 2:** Die Einstufung der Energieträger ändert sich praktisch nie, ein Snapshot wäre nur Demonstration.
- **Deadline Alerts (Airflow 3):** noch experimentell; `dagrun_timeout` mit Fehler-Alarm reicht.
- **Dashboard als Code:** Metabase ist von Hand eingerichtet, die SQL der Fragen liegt in `metabase/questions/`.
- **Eigene Rollen und Rechte, Secrets-Manager:** für einen lokalen Stack übertrieben.
- **Celery, Redis, weitere Worker:** ein DAG braucht keinen verteilten Executor.
- **Hosting der dbt-Doku:** `make dbt-docs` lokal genügt.

## Grenzen

- Sechs Wetterpunkte, ungewichtet gemittelt: eine Annäherung, kein flächendeckendes Wetterbild.
- Korrelation ist keine Ursache. Jahreszeit, Verbrauch und Brennstoffpreise wirken gleichzeitig.
- „Grün“ bezieht sich auf die Erzeugung, nicht auf den Verbrauch und nicht auf CO₂; Im- und Exporte fehlen.
- Nur der Day-Ahead-Preis der Zone DE-LU.
- Die SMARD-Schnittstelle ist öffentlich, aber nicht offiziell dokumentiert.
