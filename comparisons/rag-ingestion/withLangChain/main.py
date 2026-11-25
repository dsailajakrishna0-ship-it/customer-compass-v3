"""Starts the withLangChain ingestion backend. Settings come from the environment: PORT (19111),
SOURCE_DIR (../sample-data/documents), GOOGLE_API_KEY, GOOGLE_EMBEDDING_MODEL
(gemini-embedding-001), EMBEDDING_DIMENSIONS (768), EMBEDDING_BASE_URL (the library's default) and
QDRANT_URL (http://localhost:26333)."""

import os
from pathlib import Path

import uvicorn
from lab_common.ingest import create_ingest_app
from rag_ingestion_with_langchain import LangChainIngest


def main() -> None:
    ingest = LangChainIngest(
        Path(os.environ.get("SOURCE_DIR", "../sample-data/documents")),
        api_key=os.environ.get("GOOGLE_API_KEY", ""),
        embedding_model=os.environ.get("GOOGLE_EMBEDDING_MODEL", "gemini-embedding-001"),
        embedding_base_url=os.environ.get("EMBEDDING_BASE_URL") or None,
        dimensions=int(os.environ.get("EMBEDDING_DIMENSIONS", "768")),
        qdrant_url=os.environ.get("QDRANT_URL", "http://localhost:26333"),
    )
    port = int(os.environ.get("PORT", "19111"))
    print(f"withLangChain ingestion backend on http://localhost:{port}")
    uvicorn.run(create_ingest_app(ingest), host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
