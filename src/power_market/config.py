"""Runtime configuration from environment variables and `.env`."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    warehouse_host: str = "localhost"
    warehouse_port: int = 5432
    warehouse_db: str = "warehouse"
    warehouse_user: str = "warehouse"
    warehouse_password: SecretStr = SecretStr("")

    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minio"
    minio_secret_key: SecretStr = SecretStr("")
    minio_bucket: str = "landing"

    http_timeout_seconds: float = Field(default=30.0, gt=0)
    http_max_retries: int = Field(default=5, ge=0)
    http_backoff_base_seconds: float = Field(default=1.0, gt=0)
    http_rate_limit_per_second: float = Field(default=2.0, gt=0)
    lookback_days: int = Field(default=7, ge=0)
    backfill_start_date: str = "2023-01-01"

    alert_channel: Literal["slack", "log"] = "log"
    slack_webhook_url: SecretStr = SecretStr("")

    log_level: str = "INFO"

    @property
    def warehouse_dsn(self) -> str:
        return (
            f"host={self.warehouse_host} port={self.warehouse_port} "
            f"dbname={self.warehouse_db} user={self.warehouse_user} "
            f"password={self.warehouse_password.get_secret_value()}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
