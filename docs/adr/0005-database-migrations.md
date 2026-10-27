# 0005 — Database migrations

- **Status:** Accepted
- **Date:** 2026-10-27
- **Roadmap sub-stage:** 0.6

## Context

The V2 schema lived in two SQL files that Postgres ran once, on an empty volume (`db/init.sql`, `db/002-rag.sql`). Changing a table meant wiping the volume, and V3 adds three CRM modules (tickets, contracts, meeting notes), so schema changes are coming. The `document_chunks.embedding vector(1024)` column and the pgvector extension were unused, since vectors live in Qdrant, but they forced the pgvector Postgres image.

## Decision

Use **Alembic** with **SQLAlchemy** (as the engine) and **psycopg 3**, in `apps/api-py/migrations/`.

- Migrations are plain SQL run with `op.execute`. The app keeps using asyncpg and raw SQL; there are no ORM models and no autogenerate. SQLAlchemy is only what Alembic runs on.
- `0001` baseline schema, taken from the two V2 files. It leaves out the unused pgvector extension and column, because the plain `postgres` image cannot create the extension.
- `0002` synthetic demo data (companies, contacts, deals, interactions). It is a migration so a fresh database is built by migrations alone and the tests have their data. Later modules will get seed generators instead.
- `0003` drops the pgvector column and extension if present. It does nothing on a fresh database, and converges a V2-style database to the same schema (checked by comparing `pg_dump --schema-only` output: 0 differences).
- `docker-compose.yml`: the `db` service is plain `postgres:17.11`; a one-shot `migrate` service runs `alembic upgrade head` and the API starts only after it succeeds. `just migrate` and `just test-api` apply migrations to the local Postgres.
- `tests/test_migrations.py` builds a scratch database from empty, checks the tables and data, checks there is one head, and downgrades to base.
- `db/init.sql` and `db/002-rag.sql` are removed; they stay in V2 at tag `v2-final`.

## Alternatives considered

- Keep init scripts: cannot change an existing database, and no history of changes.
- Flyway or Liquibase: solid, but Java tools; Alembic is the Python standard and runs in the API image.
- Plain SQL files with a small runner: little to learn, and no versioning or downgrade support.
- SQLAlchemy ORM models plus autogenerate: bigger rewrite of working asyncpg code, not needed for this stage. Can be revisited if the access layer is reworked.

## Consequences

- An existing local volume made by V2's init scripts must be recreated once (`docker compose down -v`) or stamped at `0002` and upgraded; see the README.
- Downgrades past `0002` and `0003` are no-ops by design: the pgvector column is not restored, and seed rows go away when `0001` drops the tables.
- `security_audit_log` is still also created at API startup (`IF NOT EXISTS`, V2 behaviour). It can be removed once every database is migrated; left alone here to keep Stage 0 free of behaviour changes.
- Every later schema change is a new revision file with a test, reviewed in its PR.
