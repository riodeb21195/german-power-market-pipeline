# 0003 – Idempotentes Laden

Status: angenommen · 2026-10-26

## Kontext
Jeder Lauf muss beliebig oft wiederholbar sein, ohne Duplikate. SMARD korrigiert Werte nachträglich,
Open-Meteo ersetzt Modelldaten später durch Reanalyse.

## Entscheidung

**Rohdatenablage:** Schlüssel `{quelle}/{reihe}/date=YYYY-MM-DD/{sha256[:16]}.json`, Datum in
deutscher Zeit (ein SMARD-Paket beginnt Sonntag 22:00 UTC = Montag 00:00). Gleicher Inhalt ergibt
denselben Schlüssel und wird nicht erneut hochgeladen, eine Korrektur landet als neues Objekt.

**Warehouse:**
1. `COPY` aller Zeilen in eine temporäre Tabelle.
2. Deduplizierung im Paket mit `DISTINCT ON (Schlüssel)`, das letzte Vorkommen gewinnt.
3. `MERGE` in `raw.*`: neue Schlüssel einfügen, bestehende nur aktualisieren, wenn sich die
   **Datenspalten** ändern (`IS DISTINCT FROM`). Herkunftsspalten (Landing-Key, Run-ID) zählen
   nicht als Änderung. Ein Wiederholungslauf meldet deshalb 0 eingefügt und 0 aktualisiert.
4. Alles in einer Transaktion. `MERGE … RETURNING merge_action()` (ab Postgres 17) liefert die
   genauen Zahlen.

**Watermark:** `meta.checkpoints` speichert pro Quelle die letzte geladene Stunde. Ein Lauf liest
ab Watermark minus `LOOKBACK_DAYS` (7). Die Watermark läuft nur vorwärts, damit das Nachladen
eines alten Zeitraums den Fortschritt nicht zurücksetzt.

**Lauf-Protokoll und Abgleich:** `meta.pipeline_runs` hat eine Zeile pro Lauf und Quelle (Status,
Zeitraum, Zeilenzahlen, Fehler). Nach jedem Laden wird die Zahl der Quellstunden mit den Zeilen im
Ziel verglichen und in `meta.reconciliation` gespeichert. Eine Abweichung lässt den Lauf
fehlschlagen.

## Folgen
- In `raw` steht immer der neueste bekannte Wert, die Korrekturhistorie liegt in der Rohdatenablage.
- Verbindungen laufen im Autocommit-Modus mit expliziten Transaktionen, damit ein fehlgeschlagener
  Lauf seinen Status `failed` trotzdem speichern kann.
