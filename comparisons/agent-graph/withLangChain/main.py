"""Starts the withLangChain agent backend. Settings come from the environment: PORT (19142),
CRM_BASE_URL (the application, http://localhost:8001), LLM_BASE_URL (https://openrouter.ai/api/v1),
OPENROUTER_API_KEY and MODEL (meta-llama/llama-3.1-8b-instruct)."""

import os

import uvicorn
from agent_graph_with_langchain import LangChainAgent
from lab_common.agent import create_run_app
from lab_common.crm import CrmClient, CrmTools


def main() -> None:
    agent = LangChainAgent(
        CrmTools(CrmClient(os.environ.get("CRM_BASE_URL", "http://localhost:8001"))),
        base_url=os.environ.get("LLM_BASE_URL", "https://openrouter.ai/api/v1"),
        api_key=os.environ.get("OPENROUTER_API_KEY", ""),
        default_model=os.environ.get("MODEL", "meta-llama/llama-3.1-8b-instruct"),
    )
    port = int(os.environ.get("PORT", "19142"))
    print(f"withLangChain agent backend on http://localhost:{port}")
    uvicorn.run(create_run_app(agent), host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
