"""Starts the withLangGraph backend. Settings come from the environment: PORT (19102), CRM_BASE_URL
(the application, http://localhost:8001), LLM_BASE_URL (https://openrouter.ai/api/v1),
OPENROUTER_API_KEY and MODEL (meta-llama/llama-3.1-8b-instruct)."""

import os

import uvicorn
from lab_common.crm import CrmClient, CrmTools
from lab_common.server import create_app
from tool_calling_with_langgraph import LangGraphToolChat


def main() -> None:
    chat = LangGraphToolChat(
        CrmTools(CrmClient(os.environ.get("CRM_BASE_URL", "http://localhost:8001"))),
        base_url=os.environ.get("LLM_BASE_URL", "https://openrouter.ai/api/v1"),
        api_key=os.environ.get("OPENROUTER_API_KEY", ""),
        default_model=os.environ.get("MODEL", "meta-llama/llama-3.1-8b-instruct"),
    )
    port = int(os.environ.get("PORT", "19102"))
    print(f"withLangGraph tool-calling backend on http://localhost:{port}")
    uvicorn.run(create_app(chat), host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
