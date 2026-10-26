# 0004 – Datenmodell in dbt

Status: angenommen · 2026-10-26

## Kontext
Die Marts sollen die Leitfrage beantworten und ein Star-Schema bilden.

## Entscheidung

| Schicht | Materialisierung | Aufgabe |
|---|---|---|
| staging | View | umbenennen, Einheiten in den Spaltennamen (km/h → m/s), ab Analysestart filtern |
| intermediate | Tabelle | Erzeugung klassifizieren, Preis und Last zusammenführen, Vollständigkeit, Wetter-Mittel |
| marts | Tabelle | Star-Schema und zwei Analyse-Tabellen |

- **Fakten:** `fct_power_hourly` (eine Zeile pro Stunde: Preis, Last, Erzeugungssummen,
  Erneuerbaren-Anteil, Wetter) und `fct_generation_hourly` (Stunde × Energieträger, für den
  Erzeugungsmix). Zwei Tabellen, weil die Werte unterschiedliche Feinheit haben: Summen über
  Energieträger wären in einer breiten Tabelle falsch.
- **Dimensionen:** `dim_date`, `dim_hour`, `dim_energy_source`. `date_key` und `hour_key` sind
  deutsche Zeit, `hour_utc` bleibt der technische Schlüssel. Ein Tag der Zeitumstellung hat 23
  oder 25 Stunden (`dim_date.hours_in_day`), ein eigener Test prüft das.
- **Vollständigkeit:** Eine Stunde zählt nur, wenn Preis, Last und alle Pflicht-Energieträger
  vorliegen (`is_complete`). SMARD veröffentlicht Wasserkraft und „Sonstige Erneuerbare“ später,
  der Day-Ahead-Preis steht schon einen Tag vorher fest. Kernenergie ist keine Pflicht
  (Abschaltung 2023-04-15).
- **Erneuerbaren-Anteil:** erneuerbare durch gesamte Erzeugung. Pumpspeicher zählt zur Erzeugung,
  aber nicht als erneuerbar.
- **Analyse:** `mart_hourly_profile` (billigste und grünste Stunde je Jahreszeit, Wochentag und
  Uhrzeit) und `mart_weather_correlation` (Korrelationen je Jahreszeit).
- **Tests:** unique, not_null, relationships, Wertebereiche (`dbt_utils.accepted_range`, Preis
  innerhalb der SDAC-Preisgrenzen als Variablen), Aktualität, Source Freshness auf `loaded_at`,
  ein Unit-Test für Anteil und Vollständigkeit.
- **Kein SCD Typ 2:** Die Einstufung der Energieträger ändert sich praktisch nie. Ein Snapshot
  darauf wäre ein künstliches Beispiel ohne Nutzen. Die Einstufung steht im Seed `smard_series`.
- **dbt Core 1.12 statt dbt v2:** dbt v2 (Neuentwicklung in Rust) unterstützt laut Upgrade-Guide
  BigQuery, Databricks, Redshift und Snowflake, Postgres nicht. dbt v1 wird weiter voll unterstützt.

## Folgen
- Die jüngsten Stunden fehlen in den Auswertungen, bis SMARD alle Reihen veröffentlicht hat.
- Das Wetter ist ein ungewichtetes Mittel von sechs Orten.
