# 0002 – Rohdatenablage mit Silo statt MinIO

Status: angenommen · 2026-10-26

## Kontext
Die Rohdaten sollen unverändert in einem S3-kompatiblen Speicher liegen. Geplant war MinIO. Beim
Aufsetzen (Oktober 2026) zeigte sich: Das GitHub-Repository `minio/minio` ist archiviert, auf
Docker Hub gibt es `minio/minio` nicht mehr, und `quay.io/minio/minio` liefert für alle getesteten
Tags „no such manifest“.

| Option | Pro | Contra |
|---|---|---|
| `pgsty/silo` (Fork von Pigsty, AGPL-3.0) | gepflegt, feste Versions-Tags, gleiche `MINIO_*`-Variablen und S3-API | nicht der Originalhersteller |
| `cgr.dev/chainguard/minio` | gepflegt | kostenlos nur `latest`, keine festen Versionen |
| MinIO selbst bauen | Originalcode | langsam, keine Sicherheitsupdates |
| anderer S3-Server (Garage, SeaweedFS) | gepflegt | weicht weiter vom Plan ab |

## Entscheidung
`pgsty/silo` mit fester Version. Der Dienst heißt in Compose weiter `minio`. Der Python-Code nutzt
ausschließlich die S3-API über `boto3`, nichts ist MinIO- oder Silo-spezifisch.

## Folgen
- Ein Wechsel auf einen anderen S3-Speicher oder AWS ist eine Konfigurationsänderung.
- Updates des Images prüfe ich von Hand anhand der Release Notes.
