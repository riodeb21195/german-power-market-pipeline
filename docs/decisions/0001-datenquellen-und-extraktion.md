# 0001 – Datenquellen und Extraktion

Status: angenommen · 2026-10-26

## Kontext
Für die Leitfrage braucht es stündliche Preise, Erzeugung je Energieträger, Netzlast und Wetter.
Beide Quellen sind kostenlos, haben aber kein SLA.

## Entscheidung

**SMARD (Bundesnetzagentur)**
- Zwei Schritte: `chart_data/{filter}/{region}/index_hour.json` liefert die Startzeiten der
  Wochenpakete, `…/{filter}_{region}_hour_{ts}.json` die Stundenwerte einer Woche.
- 14 Reihen: Day-Ahead-Preis DE-LU (4169), Netzlast (410) und 12 Energieträger. Die Filter-IDs
  habe ich einzeln gegen die Live-API geprüft (Community-Doku: `github.com/bundesAPI/smard-api`).
- Ein Wochenpaket beginnt Montag 00:00 deutscher Zeit und hat 168 Stunden, in der Woche der
  Umstellung im Oktober 169 und im März 167. Der Code nimmt nirgends 168 an.
- `null` am Ende eines Pakets heißt „noch nicht veröffentlicht“. Diese Werte werden übersprungen,
  nie als 0 gespeichert.
- Der Preis für die Zone DE-LU existiert erst seit 2018-10-01, Kernenergie endet im Januar 2024.
  Das neueste Paket einer Reihe gilt deshalb nur eine Woche lang, sonst würde das letzte
  Kernkraft-Paket in jedes aktuelle Zeitfenster rutschen.

**Open-Meteo Archive**
- Temperatur (2 m), Wind (100 m, nah an der Nabenhöhe), Globalstrahlung, Bewölkung in UTC für
  sechs Orte: Husum, Hamburg, Berlin, Köln, Frankfurt, München.
- Ein Enddatum in der Zukunft beantwortet die API mit HTTP 400, der Client kappt deshalb auf heute.
- Die jüngsten Tage sind Modelldaten, die später durch ERA5-Reanalyse ersetzt werden.

**Robustheit**
- Timeout pro Anfrage; Wiederholung nur bei Timeout, Verbindungsfehler, 429 und 5xx, mit
  exponentiellem Backoff und Jitter (höchstens 60 s), `Retry-After` hat Vorrang. Andere 4xx
  schlagen sofort fehl.
- Gleichmäßiges Tempolimit (Standard 2 Anfragen pro Sekunde).
- Jede Antwort wird vor dem Speichern gegen ein Pydantic-Modell mit `extra="forbid"` geprüft:
  fehlende oder neue Felder, andere Typen, andere Einheiten oder keine UTC-Antwort führen zu einem
  `SchemaDriftError` mit lesbarer Liste der Abweichungen. Bewusst streng: lieber ein
  fehlgeschlagener Lauf als still falsch interpretierte Daten.
- Eigene, kleine Retry-Logik statt `tenacity`: keine weitere Abhängigkeit, und `sleep` lässt sich
  in Tests ersetzen.

## Folgen
- Formatänderungen der Quelle bedeuten: Modell und aufgezeichnete Test-Antworten in einem Commit
  anpassen.
- Sechs Wetterpunkte sind eine Vereinfachung gegenüber einem flächengewichteten Wetterbild.
