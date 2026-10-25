-- Stage 3 — Basic RAG schema.
-- Adds document storage, chunk-level embeddings, and ingestion run history.
-- This file only runs automatically on a fresh (empty) database volume,
-- the same as 001-init.sql. Against an existing volume, apply it manually, e.g.
--   docker exec -i customer-compass-db psql -U customer_compass -d customer_compass < db/002-rag.sql

-- Legacy pgvector: live embeddings are in Qdrant now; document_chunks.embedding below is unused
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE documents (
  id SERIAL PRIMARY KEY,
  source_path TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL,
  doc_type TEXT NOT NULL CHECK (doc_type IN ('email', 'call', 'note', 'support', 'product')),
  company_id INTEGER REFERENCES companies(id),
  content TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- mxbai-embed-large produces 1024-dimension embeddings.
CREATE TABLE document_chunks (
  id SERIAL PRIMARY KEY,
  document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  chunk_index INTEGER NOT NULL,
  content TEXT NOT NULL,
  char_start INTEGER NOT NULL,
  char_end INTEGER NOT NULL,
  embedding vector(1024),
  UNIQUE (document_id, chunk_index)
);

-- No ANN index (ivfflat/hnsw) yet: the corpus is tiny for learning purposes,
-- so an exact <=> scan over all chunks is fast and simpler to reason about.
-- Stage 5 revisits indexing as retrieval quality/scale become the focus.

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
