"""Landing zone: raw API payloads, stored byte-for-byte in S3-compatible storage.

Keys are partitioned by the date the data belongs to and end with a hash of the payload,
e.g. `smard/4169_DE-LU/date=2026-10-19/3f1c0a9b2d4e5f60.json`. The same payload always gets the
same key, so a re-run does not store it twice; a corrected payload lands as a new object.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from power_market.config import Settings

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class LandedObject:
    key: str
    created: bool  # False if the identical payload was already there


def landing_key(prefix: str, partition_date: date, payload: bytes) -> str:
    digest = hashlib.sha256(payload).hexdigest()[:16]
    return f"{prefix.strip('/')}/date={partition_date.isoformat()}/{digest}.json"


def make_s3_client(settings: Settings) -> S3Client:
    return boto3.client(
        "s3",
        endpoint_url=f"http://{settings.minio_endpoint}",
        aws_access_key_id=settings.minio_access_key,
        aws_secret_access_key=settings.minio_secret_key.get_secret_value(),
        region_name="us-east-1",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


class LandingZone:
    def __init__(self, s3: S3Client, bucket: str) -> None:
        self._s3 = s3
        self._bucket = bucket

    def ensure_bucket(self) -> None:
        try:
            self._s3.head_bucket(Bucket=self._bucket)
        except ClientError:
            self._s3.create_bucket(Bucket=self._bucket)

    def _exists(self, key: str) -> bool:
        try:
            self._s3.head_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise
        return True

    def put(
        self,
        prefix: str,
        partition_date: date,
        payload: bytes,
        metadata: dict[str, str] | None = None,
    ) -> LandedObject:
        key = landing_key(prefix, partition_date, payload)
        if self._exists(key):
            return LandedObject(key, created=False)
        self._s3.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=payload,
            ContentType="application/json",
            Metadata=metadata or {},
        )
        log.info("landed raw payload", extra={"key": key, "bytes": len(payload)})
        return LandedObject(key, created=True)

    def get(self, key: str) -> bytes:
        return self._s3.get_object(Bucket=self._bucket, Key=key)["Body"].read()

    def list_keys(self, prefix: str = "") -> list[str]:
        paginator = self._s3.get_paginator("list_objects_v2")
        keys: list[str] = []
        for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
            keys.extend(obj["Key"] for obj in page.get("Contents", []) if "Key" in obj)
        return sorted(keys)
