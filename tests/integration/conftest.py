"""Real Postgres and S3 (Silo/MinIO) containers for integration tests, one per test session."""

from __future__ import annotations

import time
import uuid
from collections.abc import Iterator

import httpx
import psycopg
import pytest
from pydantic import SecretStr
from testcontainers.community.postgres import PostgresContainer
from testcontainers.core.container import DockerContainer

from power_market.config import Settings
from power_market.landing import LandingZone, make_s3_client
from power_market.warehouse import connect, ensure_schema

POSTGRES_IMAGE = "postgres:18.6-alpine"
S3_IMAGE = "pgsty/silo:RELEASE.2026-10-18T00-00-00Z"
S3_USER, S3_PASSWORD = "testuser", "testpassword123"


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark everything below tests/integration so `-m "not integration"` skips Docker tests."""
    for item in items:
        if "tests/integration" in str(item.path):
            item.add_marker(pytest.mark.integration)


@pytest.fixture(scope="session")
def postgres() -> Iterator[PostgresContainer]:
    with PostgresContainer(
        POSTGRES_IMAGE, username="warehouse", password="warehouse", dbname="warehouse"
    ) as container:
        yield container


@pytest.fixture(scope="session")
def s3_endpoint() -> Iterator[str]:
    container = (
        DockerContainer(S3_IMAGE)
        .with_command("silo server /data")
        .with_env("MINIO_ROOT_USER", S3_USER)
        .with_env("MINIO_ROOT_PASSWORD", S3_PASSWORD)
        .with_exposed_ports(9000)
    )
    with container:
        endpoint = f"{container.get_container_host_ip()}:{container.get_exposed_port(9000)}"
        deadline = time.monotonic() + 60
        while True:
            try:
                if httpx.get(f"http://{endpoint}/minio/health/live", timeout=2).is_success:
                    break
            except httpx.HTTPError:
                pass
            if time.monotonic() > deadline:
                raise RuntimeError("S3 container did not become healthy")
            time.sleep(0.5)
        yield endpoint


@pytest.fixture(scope="session")
def settings(postgres: PostgresContainer, s3_endpoint: str) -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        warehouse_host=postgres.get_container_host_ip(),
        warehouse_port=int(postgres.get_exposed_port(5432)),
        warehouse_db="warehouse",
        warehouse_user="warehouse",
        warehouse_password=SecretStr("warehouse"),
        minio_endpoint=s3_endpoint,
        minio_access_key=S3_USER,
        minio_secret_key=SecretStr(S3_PASSWORD),
        minio_bucket="landing-test",
    )


@pytest.fixture
def conn(settings: Settings) -> Iterator[psycopg.Connection]:
    """Fresh schema for every test: drop and re-create raw/meta."""
    connection = connect(settings)
    connection.execute("drop schema if exists raw cascade")
    connection.execute("drop schema if exists meta cascade")
    ensure_schema(connection)
    yield connection
    connection.close()


@pytest.fixture
def landing(settings: Settings) -> LandingZone:
    zone = LandingZone(make_s3_client(settings), f"landing-{uuid.uuid4().hex[:8]}")
    zone.ensure_bucket()
    return zone
