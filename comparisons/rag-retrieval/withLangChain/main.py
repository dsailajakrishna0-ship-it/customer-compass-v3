"""Starts the withLangChain retrieval backend. Settings come from the environment: PORT (19121),
GOOGLE_API_KEY, GOOGLE_EMBEDDING_MODEL (gemini-embedding-001), EMBEDDING_DIMENSIONS (768),
EMBEDDING_BASE_URL (the library's default) and QDRANT_URL (http://localhost:26333). Search the
collection that the withLangChain ingestion (port 19111) filled."""

import os

import uvicorn
from lab_common.retrieve import create_retrieve_app
from rag_retrieval_with_langchain import LangChainRetrieve


def main() -> None:
    retrieve = LangChainRetrieve(
        api_key=os.environ.get("GOOGLE_API_KEY", ""),
        embedding_model=os.environ.get("GOOGLE_EMBEDDING_MODEL", "gemini-embedding-001"),
        embedding_base_url=os.environ.get("EMBEDDING_BASE_URL"),
        dimensions=int(os.environ.get("EMBEDDING_DIMENSIONS", "768")),
        qdrant_url=os.environ.get("QDRANT_URL", "http://localhost:26333"),
    )
    port = int(os.environ.get("PORT", "19121"))
    print(f"withLangChain retrieval backend on http://localhost:{port}")
    uvicorn.run(create_retrieve_app(retrieve), host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
