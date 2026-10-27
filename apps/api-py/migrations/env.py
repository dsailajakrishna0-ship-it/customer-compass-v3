"""Alembic environment: runs migrations as plain SQL against DATABASE_URL.

The app talks to Postgres with asyncpg and raw SQL; SQLAlchemy is only the engine
Alembic needs, so there are no ORM models and no autogenerate.
"""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Same variable and default as app/db.py, read at run time so tests can point it elsewhere
url = os.environ.get(
    "DATABASE_URL",
    "postgresql://customer_compass:customer_compass_dev@localhost:5432/customer_compass",
)
# asyncpg uses a plain postgresql:// URL; SQLAlchemy needs the psycopg driver named
if url.startswith("postgresql://"):
    url = url.replace("postgresql://", "postgresql+psycopg://", 1)

engine = create_engine(url, poolclass=pool.NullPool)
with engine.connect() as connection:
    context.configure(connection=connection, target_metadata=None)
    with context.begin_transaction():
        context.run_migrations()
