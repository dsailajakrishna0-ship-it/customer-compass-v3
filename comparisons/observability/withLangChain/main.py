"""Starts the observed withLangChain tool-calling backend on port 19131. Settings as for the
tool-calling backend, plus TELEMETRY_ENABLED=true to record signals (then
GET /api/v1/observability/recent shows the most recent traces and the metrics)."""

import os

import uvicorn
from lab_common.crm import CrmClient, CrmTools
from lab_common.server import create_app
from lab_common.telemetry import NoObserver, Telemetry
from observed_langchain import ObservedLangChainToolChat


def main() -> None:
    telemetry = Telemetry() if os.environ.get("TELEMETRY_ENABLED", "").lower() == "true" else None
    chat = ObservedLangChainToolChat(
        CrmTools(CrmClient(os.environ.get("CRM_BASE_URL", "http://localhost:8001"))),
        base_url=os.environ.get("LLM_BASE_URL", "https://openrouter.ai/api/v1"),
        api_key=os.environ.get("OPENROUTER_API_KEY", ""),
        default_model=os.environ.get("MODEL", "meta-llama/llama-3.1-8b-instruct"),
    )
    chat.observe_with(telemetry or NoObserver())
    port = int(os.environ.get("PORT", "19131"))
    print(
        f"observed withLangChain backend on http://localhost:{port} (observation {'on' if telemetry else 'off'})"
    )
    uvicorn.run(create_app(chat, telemetry), host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
