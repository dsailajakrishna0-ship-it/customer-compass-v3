"""Tool calling with LangGraph: we draw the loop ourselves as a StateGraph.

Two nodes (the model, the tools), an edge back from the tools to the model, and a conditional edge
after the model: tools if it asked for any and the round limit allows, a last answer without tools
if it asked for more than the limit allows, otherwise the end. The tools are plain LangChain
`@tool` functions run by LangGraph's prebuilt `ToolNode`. Decisions and measurements: docs/adr/0037.
"""

from __future__ import annotations

import time
from typing import Literal

from lab_common.chat import Message, Result, UnavailableError
from lab_common.crm import (
    MAX_CALLS_MESSAGE,
    MAX_ROUNDS,
    SYSTEM_PROMPT,
    CrmTools,
    wrap_untrusted,
)
from lab_common.lc import read_result
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from langchain_core.tools import BaseTool, tool
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode


class ToolState(MessagesState):
    rounds: int  # how many times the tools have run


def build_tools(crm_tools: CrmTools) -> list[BaseTool]:
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


def build_graph(llm: BaseChatModel, tools: list[BaseTool]):
    with_tools = llm.bind_tools(tools)

    def call_model(state: ToolState) -> dict[str, list[AnyMessage]]:
        reply = with_tools.invoke([SystemMessage(SYSTEM_PROMPT), *state["messages"]])
        return {"messages": [reply]}

    def run_tools(state: ToolState) -> dict[str, int]:
        return {"rounds": state.get("rounds", 0) + 1}

    def final_answer(state: ToolState) -> dict[str, list[AnyMessage]]:
        # The model still wants tools after MAX_ROUNDS: ask once more with the tools switched off.
        # The unanswered tool-call message is dropped so the conversation stays valid.
        history = list(state["messages"])[:-1]
        reply = llm.invoke(
            [SystemMessage(SYSTEM_PROMPT), *history, HumanMessage(MAX_CALLS_MESSAGE)]
        )
        return {"messages": [reply]}

    def route(state: ToolState) -> Literal["tools", "final_answer", "__end__"]:
        last = state["messages"][-1]
        if not (isinstance(last, AIMessage) and last.tool_calls):
            return END
        return "tools" if state.get("rounds", 0) < MAX_ROUNDS else "final_answer"

    graph = StateGraph(ToolState)
    graph.add_node("model", call_model)
    graph.add_node("tools", ToolNode(tools))
    graph.add_node("count_round", run_tools)
    graph.add_node("final_answer", final_answer)
    graph.add_edge(START, "model")
    graph.add_conditional_edges(
        "model", route, {"tools": "tools", "final_answer": "final_answer", END: END}
    )
    graph.add_edge("tools", "count_round")
    graph.add_edge("count_round", "model")
    graph.add_edge("final_answer", END)
    return graph.compile()


class LangGraphToolChat:
    approach = "withLangGraph"

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
        self._model = model
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

    def _run(self, graph, payload):  # noqa: ANN001, ANN202 - a hook the observed variant overrides
        return graph.invoke(payload)

    def answer(self, messages: list[Message], model: str | None) -> Result:
        llm, name = self._llm(model)
        graph = build_graph(llm, self._tools)
        started = time.monotonic()
        start = [
            HumanMessage(m.content) if m.role == "user" else AIMessage(m.content) for m in messages
        ]
        try:
            state = self._run(graph, {"messages": start, "rounds": 0})
        except UnavailableError:
            raise
        except Exception as exc:
            raise UnavailableError(f"The model call failed ({type(exc).__name__}).") from exc
        return read_result(state["messages"], name, started)
