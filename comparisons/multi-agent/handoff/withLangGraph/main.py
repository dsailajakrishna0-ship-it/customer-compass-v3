"""Starts the handoff multi-agent backend (LangGraph). Settings come from the environment: PORT (19154),
CRM_BASE_URL (the application, http://localhost:8001), LLM_BASE_URL (https://openrouter.ai/api/v1),
OPENROUTER_API_KEY and MODEL (meta-llama/llama-3.1-8b-instruct)."""

import os

import uvicorn
from handoff_with_langgraph import HandoffTeam
from lab_common.crm import CrmClient, CrmTools
from lab_common.team import TeamModel, create_team_app


def main() -> None:
    model = TeamModel(
        base_url=os.environ.get("LLM_BASE_URL", "https://openrouter.ai/api/v1"),
        api_key=os.environ.get("OPENROUTER_API_KEY", ""),
        default_model=os.environ.get("MODEL", "meta-llama/llama-3.1-8b-instruct"),
    )
    tools = CrmTools(CrmClient(os.environ.get("CRM_BASE_URL", "http://localhost:8001")))
    port = int(os.environ.get("PORT", "19154"))
    print(f"handoff multi-agent backend on http://localhost:{port}")
    uvicorn.run(
        create_team_app(HandoffTeam(tools, model)), host="127.0.0.1", port=port, log_level="warning"
    )


if __name__ == "__main__":
    main()
