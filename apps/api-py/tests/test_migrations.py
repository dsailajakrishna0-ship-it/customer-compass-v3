"""Migrations build the whole schema from an empty database (needs Postgres, like test_health)."""

import os
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.engine import make_url

from app.config import reset_settings

API_DIR = Path(__file__).resolve().parent.parent
BASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://customer_compass:customer_compass_dev@localhost:5432/customer_compass",
)
SCRATCH_DB = "cc_migration_test"
EXPECTED_TABLES = {
    "companies",
    "contacts",
    "deals",
    "interactions",
    "tasks",
    "tool_audit_log",
    "security_audit_log",
    "documents",
    "document_chunks",
    "ingestion_runs",
}


def _alembic_config() -> Config:
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "migrations"))
    return config


def _query(url: str, sql: str) -> list[tuple]:
    with psycopg.connect(url, autocommit=True) as conn:
        return conn.execute(sql).fetchall()


@pytest.fixture
def scratch_database_url(monkeypatch):
    """An empty database, created for one test and dropped afterwards."""
    base = make_url(BASE_URL).set(drivername="postgresql")
    admin_url = base.render_as_string(hide_password=False)
    scratch_url = base.set(database=SCRATCH_DB).render_as_string(hide_password=False)
    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {SCRATCH_DB}")
        conn.execute(f"CREATE DATABASE {SCRATCH_DB}")
    monkeypatch.setenv("DATABASE_URL", scratch_url)
    reset_settings()
    yield scratch_url
    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {SCRATCH_DB} WITH (FORCE)")


def test_there_is_a_single_migration_head():
    assert len(ScriptDirectory.from_config(_alembic_config()).get_heads()) == 1


def test_fresh_database_is_built_by_migrations(scratch_database_url):
    command.upgrade(_alembic_config(), "head")

    tables = {
        r[0]
        for r in _query(
            scratch_database_url, "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        )
    }
    assert tables == EXPECTED_TABLES | {"alembic_version"}
    assert _query(scratch_database_url, "SELECT count(*) FROM companies") == [(7,)]
    # the unused pgvector column and extension are gone
    assert _query(
        scratch_database_url, "SELECT count(*) FROM pg_extension WHERE extname = 'vector'"
    ) == [(0,)]
    assert _query(
        scratch_database_url,
        "SELECT count(*) FROM information_schema.columns WHERE table_name = 'document_chunks' AND column_name = 'embedding'",
    ) == [(0,)]


def test_downgrade_to_base_removes_everything(scratch_database_url):
    config = _alembic_config()
    command.upgrade(config, "head")
    command.downgrade(config, "base")

    tables = {
        r[0]
        for r in _query(
            scratch_database_url, "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        )
    }
    assert tables == {"alembic_version"}
