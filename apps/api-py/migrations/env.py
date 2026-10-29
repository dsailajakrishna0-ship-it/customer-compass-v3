"""Alembic environment: runs migrations as plain SQL against DATABASE_URL.

The app talks to Postgres with asyncpg and raw SQL; SQLAlchemy is only the engine
Alembic needs, so there are no ORM models and no autogenerate.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from app.config import get_settings

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The same setting the API uses (DATABASE_URL); tests point it elsewhere and call reset_settings()
url = get_settings().database_url
# asyncpg uses a plain postgresql:// URL; SQLAlchemy needs the psycopg driver named
if url.startswith("postgresql://"):
    url = url.replace("postgresql://", "postgresql+psycopg://", 1)

engine = create_engine(url, poolclass=pool.NullPool)
with engine.connect() as connection:
    context.configure(connection=connection, target_metadata=None)
    with context.begin_transaction():
        context.run_migrations()
