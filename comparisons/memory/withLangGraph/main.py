"""Starts the withLangGraph conversation-memory backend. Settings come from the environment: PORT (19161),
LLM_BASE_URL (https://openrouter.ai/api/v1), OPENROUTER_API_KEY, MODEL (meta-llama/llama-3.1-8b-instruct)
and the limits MEMORY_MAX_MESSAGES, MEMORY_MAX_CHARS, MEMORY_TTL_HOURS, MEMORY_MAX_CONVERSATIONS,
MEMORY_MAX_STORED_MESSAGES (defaults 20, 16000, 24, 1000, 200)."""

import os

import uvicorn
from lab_common.memory import MemoryLimits, create_memory_app
from memory_with_langgraph import LangGraphMemoryChat


def main() -> None:
    memory = LangGraphMemoryChat(
        MemoryLimits.from_environment(),
        base_url=os.environ.get("LLM_BASE_URL", "https://openrouter.ai/api/v1"),
        api_key=os.environ.get("OPENROUTER_API_KEY", ""),
        default_model=os.environ.get("MODEL", "meta-llama/llama-3.1-8b-instruct"),
    )
    port = int(os.environ.get("PORT", "19161"))
    print(f"withLangGraph memory backend on http://localhost:{port}")
    uvicorn.run(create_memory_app(memory), host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
