"""Baseline schema: CRM, audit and document tables.

Taken from V2's db/init.sql and db/002-rag.sql. The unused pgvector extension and
document_chunks.embedding column are left out; 0003 removes them from databases
that were created by the old init scripts.

Revision ID: 0001
Revises:
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

SCHEMA = """
CREATE TABLE companies (
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL,
  industry TEXT NOT NULL,
  website TEXT,
  relationship_status TEXT NOT NULL CHECK (relationship_status IN ('lead', 'customer', 'former_customer')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE contacts (
  id SERIAL PRIMARY KEY,
  company_id INTEGER NOT NULL REFERENCES companies(id),
  full_name TEXT NOT NULL,
  job_title TEXT,
  email TEXT NOT NULL
);

CREATE TABLE deals (
  id SERIAL PRIMARY KEY,
  company_id INTEGER NOT NULL REFERENCES companies(id),
  name TEXT NOT NULL,
  amount NUMERIC(12, 2) NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('open', 'won', 'lost')),
  expected_close_date DATE
);

CREATE TABLE interactions (
  id SERIAL PRIMARY KEY,
  company_id INTEGER NOT NULL REFERENCES companies(id),
  interaction_type TEXT NOT NULL CHECK (interaction_type IN ('email', 'call', 'meeting', 'note', 'support')),
  subject TEXT NOT NULL,
  occurred_at TIMESTAMPTZ NOT NULL,
  summary TEXT NOT NULL
);

CREATE TABLE tasks (
  id SERIAL PRIMARY KEY,
  company_id INTEGER NOT NULL REFERENCES companies(id),
  note TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'done')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE tool_audit_log (
  id SERIAL PRIMARY KEY,
  tool_name TEXT NOT NULL,
  arguments JSONB NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('executed', 'proposed', 'confirmed', 'error')),
  result_summary TEXT,
  company_id INTEGER REFERENCES companies(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE security_audit_log (
  id SERIAL PRIMARY KEY,
  event_type TEXT NOT NULL CHECK (event_type IN ('input', 'document', 'tool', 'output')),
  endpoint TEXT NOT NULL,
  pattern TEXT NOT NULL,
  location TEXT NOT NULL,
  excerpt TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE documents (
  id SERIAL PRIMARY KEY,
  source_path TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL,
  doc_type TEXT NOT NULL CHECK (doc_type IN ('email', 'call', 'note', 'support', 'product')),
  company_id INTEGER REFERENCES companies(id),
  content TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE document_chunks (
  id SERIAL PRIMARY KEY,
  document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  chunk_index INTEGER NOT NULL,
  content TEXT NOT NULL,
  char_start INTEGER NOT NULL,
  char_end INTEGER NOT NULL,
  UNIQUE (document_id, chunk_index)
);

CREATE TABLE ingestion_runs (
  id SERIAL PRIMARY KEY,
  started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  completed_at TIMESTAMPTZ,
  status TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'completed', 'failed')),
  embedding_model TEXT NOT NULL,
  documents_processed INTEGER NOT NULL DEFAULT 0,
  chunks_created INTEGER NOT NULL DEFAULT 0,
  error TEXT
);
"""


def upgrade() -> None:
    for statement in SCHEMA.split(";"):
        if statement.strip():
            op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ingestion_runs CASCADE")
    op.execute("DROP TABLE IF EXISTS document_chunks CASCADE")
    op.execute("DROP TABLE IF EXISTS documents CASCADE")
    op.execute("DROP TABLE IF EXISTS security_audit_log CASCADE")
    op.execute("DROP TABLE IF EXISTS tool_audit_log CASCADE")
    op.execute("DROP TABLE IF EXISTS tasks CASCADE")
    op.execute("DROP TABLE IF EXISTS interactions CASCADE")
    op.execute("DROP TABLE IF EXISTS deals CASCADE")
    op.execute("DROP TABLE IF EXISTS contacts CASCADE")
    op.execute("DROP TABLE IF EXISTS companies CASCADE")
