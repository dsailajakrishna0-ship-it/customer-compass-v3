"""Tool calling with LangChain: `@tool` for the tools, `create_agent` for the loop.

LangChain 1.x builds the whole loop for us (model call, run the tools it asked for, model call
again, until it answers). What we add: the system prompt, the data wrapper around tool results,
and a cap on model rounds (a middleware). Decisions and measurements: docs/adr/0037.
"""

from __future__ import annotations

import time

from lab_common.chat import Message, Result, UnavailableError
from lab_common.crm import MAX_ROUNDS, SYSTEM_PROMPT, CrmTools, wrap_untrusted
from lab_common.lc import read_result
from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from langchain_core.tools import BaseTool, tool


def build_tools(crm_tools: CrmTools) -> list[BaseTool]:
    """The two tools. `@tool` writes the JSON Schema from the signature and the docstring."""

    @tool(parse_docstring=True)
    def get_company_summary(company_name: str) -> str:
        """Get verified CRM facts for a company: industry, relationship status, open deals, and won/lost deal counts.

        Args:
            company_name: The company's name, as the user wrote it.
        """
        return wrap_untrusted(crm_tools.call("get_company_summary", company_name))

    @tool(parse_docstring=True)
    def get_open_deals(company_name: str) -> str:
        """Get only the open deals for a company (name, amount, status, expected close date).

        Args:
            company_name: The company's name, as the user wrote it.
        """
        return wrap_untrusted(crm_tools.call("get_open_deals", company_name))

    return [get_company_summary, get_open_deals]


def to_langchain_messages(messages: list[Message]) -> list[AnyMessage]:
    return [HumanMessage(m.content) if m.role == "user" else AIMessage(m.content) for m in messages]


class LangChainToolChat:
    approach = "withLangChain"

    def __init__(
        self,
        crm_tools: CrmTools,
        *,
        model: BaseChatModel | None = None,
        base_url: str = "https://openrouter.ai/api/v1",
        api_key: str = "",
        default_model: str = "meta-llama/llama-3.1-8b-instruct",
    ) -> None:
        self._tools = build_tools(crm_tools)
        self._model = model  # a stand-in in tests; None means the real one below
        self._base_url = base_url
        self._api_key = api_key
        self._default_model = default_model

    def _llm(self, model: str | None) -> tuple[BaseChatModel, str]:
        name = model or self._default_model
        if self._model is not None:
            return self._model, name
        if not self._api_key.strip():
            raise UnavailableError("OPENROUTER_API_KEY is not set. Put it in the environment.")
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=name, base_url=self._base_url, api_key=self._api_key, max_retries=0
        ), name

    def answer(self, messages: list[Message], model: str | None) -> Result:
        llm, name = self._llm(model)
        agent = create_agent(
            llm,
            self._tools,
            system_prompt=SYSTEM_PROMPT,
            # MAX_ROUNDS rounds may ask for tools; the model call after them is the last one.
            middleware=[ModelCallLimitMiddleware(run_limit=MAX_ROUNDS + 1, exit_behavior="end")],
        )
        started = time.monotonic()
        try:
            state = agent.invoke({"messages": to_langchain_messages(messages)})
        except UnavailableError:
            raise
        except Exception as exc:
            raise UnavailableError(f"The model call failed ({type(exc).__name__}).") from exc
        return read_result(state["messages"], name, started)
