"""Both memory approaches against a scripted model and a clock the tests move: no key, no network.
The same rules (ADR 0036), the history kept two ways. See docs/adr/0042."""

import threading
from datetime import UTC, datetime, timedelta

import pytest
from lab_common.chat import Message, UnavailableError
from lab_common.memory import ConversationNotFoundError, MemoryLimits
from lab_common.testing import ai, scripted
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from memory_with_langchain import LangChainMemoryChat
from memory_with_langgraph import LangGraphMemoryChat

APPROACHES = [LangChainMemoryChat, LangGraphMemoryChat]


class Clock:
    def __init__(self):
        self.now = datetime(2026, 11, 27, 12, 0, tzinfo=UTC)

    def __call__(self):
        return self.now

    def advance(self, **kwargs):
        self.now += timedelta(**kwargs)


def replies(n):
    return [ai(f"answer {i}") for i in range(1, n + 1)]


def make(approach, limits=None, n=8, clock=None):
    model = scripted(*replies(n))
    clock = clock or Clock()
    chat = approach(limits or MemoryLimits(), clock=clock, model=model)
    return chat, model, clock


def ask(chat, cid, text="hi"):
    return chat.chat(cid, [Message("user", text)], None)


def texts(call):
    return [(type(m).__name__, m.content) for m in call]


@pytest.mark.parametrize("approach", APPROACHES)
def test_a_new_conversation_has_an_id_an_expiry_and_no_messages(approach):
    chat, _, clock = make(approach)
    created = chat.create()
    assert created.expires_at == clock.now + timedelta(hours=24)
    assert chat.get(created.conversation_id).messages == []


@pytest.mark.parametrize("approach", APPROACHES)
def test_a_turn_stores_the_new_messages_and_the_answer_and_the_next_turn_sends_them_first(approach):
    chat, model, _ = make(approach)
    cid = chat.create().conversation_id
    first = ask(chat, cid, "my name is Maya")
    assert (first.message, first.messages_used, first.messages_stored) == ("answer 1", 0, 2)
    second = ask(chat, cid, "what is my name?")
    assert (second.messages_used, second.messages_stored) == (2, 4)
    sent = model.seen[1]
    assert isinstance(sent[0], SystemMessage)
    assert texts(sent[1:]) == [
        ("HumanMessage", "my name is Maya"),
        ("AIMessage", "answer 1"),
        ("HumanMessage", "what is my name?"),
    ]
    stored = chat.get(cid).messages
    assert [(m.role, m.content) for m in stored] == [
        ("user", "my name is Maya"),
        ("assistant", "answer 1"),
        ("user", "what is my name?"),
        ("assistant", "answer 2"),
    ]


@pytest.mark.parametrize("approach", APPROACHES)
def test_the_window_is_the_most_recent_messages_then_the_oldest_dropped_until_the_characters_fit(
    approach,
):
    chat, model, _ = make(approach, MemoryLimits(max_messages=3, max_chars=1000))
    cid = chat.create().conversation_id
    for text in ("one", "two", "three"):
        ask(chat, cid, text)
    answer = ask(chat, cid, "four")
    assert answer.messages_used == 3  # six stored, the last three sent
    assert [m.content for m in model.seen[3][1:-1]] == ["answer 2", "three", "answer 3"]

    small, model2, _ = make(approach, MemoryLimits(max_messages=20, max_chars=20))
    cid = small.create().conversation_id
    ask(small, cid, "a" * 15)  # stores 15 + len("answer 1") = 23 characters
    ask(small, cid, "b")
    # the history is 23 characters, over 20: the oldest (the question) is left out first
    assert [m.content for m in model2.seen[1][1:-1]] == ["answer 1"]


@pytest.mark.parametrize("approach", APPROACHES)
def test_one_message_longer_than_the_character_limit_leaves_no_history(approach):
    chat, model, _ = make(approach, MemoryLimits(max_chars=5))
    cid = chat.create().conversation_id
    ask(chat, cid, "x" * 50)
    assert ask(chat, cid, "next").messages_used == 0


@pytest.mark.parametrize("approach", APPROACHES)
def test_a_failed_turn_stores_nothing_and_the_conversation_still_works(approach):
    chat, model, _ = make(approach, n=0)
    cid = chat.create().conversation_id
    with pytest.raises(UnavailableError) as info:
        ask(chat, cid, "lost")
    assert "AssertionError" in str(info.value) and "more often than" not in str(info.value)
    assert chat.get(cid).messages == []
    model.script.append(ai("fine"))
    assert (ask(chat, cid, "again").messages_used, chat.get(cid).messages[0].content) == (
        0,
        "again",
    )


@pytest.mark.parametrize("approach", APPROACHES)
def test_an_unknown_conversation_is_not_found_for_every_operation(approach):
    chat, _, _ = make(approach)
    cid = "0b8f7c2e-6a51-4c0e-9d57-7f1f0b3c1a11"
    for call in (lambda: ask(chat, cid), lambda: chat.get(cid), lambda: chat.delete(cid)):
        with pytest.raises(ConversationNotFoundError):
            call()


@pytest.mark.parametrize("approach", APPROACHES)
def test_a_deleted_conversation_is_gone(approach):
    chat, _, _ = make(approach)
    cid = chat.create().conversation_id
    ask(chat, cid)
    chat.delete(cid)
    with pytest.raises(ConversationNotFoundError):
        chat.get(cid)


@pytest.mark.parametrize("approach", APPROACHES)
def test_a_conversation_expires_after_its_last_use_and_only_a_turn_extends_it(approach):
    chat, _, clock = make(approach, MemoryLimits(ttl=timedelta(hours=1)))
    cid = chat.create().conversation_id
    clock.advance(minutes=50)
    chat.get(cid)  # reading does not extend the life
    clock.advance(minutes=9)
    ask(chat, cid)  # a turn does: it now lives until 70 minutes after the creation
    clock.advance(minutes=50)
    assert chat.get(cid).expires_at == clock.now - timedelta(minutes=50) + timedelta(hours=1)
    clock.advance(minutes=11)
    with pytest.raises(ConversationNotFoundError):
        chat.get(cid)


@pytest.mark.parametrize("approach", APPROACHES)
def test_the_cap_removes_the_least_recently_used_conversation(approach):
    chat, _, _ = make(approach, MemoryLimits(max_conversations=2))
    first = chat.create().conversation_id
    second = chat.create().conversation_id
    ask(chat, first)  # first is now the more recently used
    third = chat.create().conversation_id
    with pytest.raises(ConversationNotFoundError):
        chat.get(second)
    assert chat.get(first).messages and chat.get(third).messages == []


@pytest.mark.parametrize("approach", APPROACHES)
def test_a_conversation_keeps_at_most_the_stored_bound_and_the_oldest_go_first(approach):
    chat, _, _ = make(approach, MemoryLimits(max_stored_messages=4))
    cid = chat.create().conversation_id
    ask(chat, cid, "q1")
    ask(chat, cid, "q2")
    last = ask(chat, cid, "q3")
    assert last.messages_stored == 4
    assert [m.content for m in chat.get(cid).messages] == ["q2", "answer 2", "q3", "answer 3"]


@pytest.mark.parametrize("approach", APPROACHES)
def test_a_conversation_deleted_during_the_call_stays_deleted_and_the_answer_is_still_returned(
    approach,
):
    chat, model, _ = make(approach)
    cid = chat.create().conversation_id
    model.on_call = lambda: chat.delete(cid)
    answer = ask(chat, cid)
    assert (answer.message, answer.messages_stored) == ("answer 1", 0)
    with pytest.raises(ConversationNotFoundError):
        chat.get(cid)


@pytest.mark.parametrize("approach", APPROACHES)
def test_no_lock_is_held_while_the_model_is_called(approach):
    chat, model, _ = make(approach)
    cid = chat.create().conversation_id
    other = chat.create().conversation_id
    inside, release = threading.Event(), threading.Event()
    model.on_call = lambda: (inside.set(), release.wait(5))
    worker = threading.Thread(target=lambda: ask(chat, cid))
    worker.start()
    assert inside.wait(5)
    try:
        # while the model is "thinking": other conversations, and this one, can be read and created
        assert chat.get(other).messages == []
        assert chat.get(cid).messages == []
        chat.create()
    finally:
        release.set()
        worker.join(5)
    assert len(chat.get(cid).messages) == 2


@pytest.mark.parametrize("approach", APPROACHES)
def test_no_key_means_no_call(approach):
    chat = approach(MemoryLimits())
    cid = chat.create().conversation_id
    with pytest.raises(UnavailableError, match="OPENROUTER_API_KEY"):
        ask(chat, cid)


def test_the_limits_come_from_the_environment_and_must_be_positive():
    limits = MemoryLimits.from_environment({"MEMORY_MAX_MESSAGES": "5", "MEMORY_TTL_HOURS": "2"})
    assert (limits.max_messages, limits.ttl, limits.max_chars) == (5, timedelta(hours=2), 16_000)
    with pytest.raises(ValueError):
        MemoryLimits(max_messages=0)


# What the libraries did on their own (measured).


def test_measured_the_langchain_history_loads_everything_and_the_window_is_ours_to_make(
    crm_tools=None,
):
    from langchain_core.chat_history import InMemoryChatMessageHistory
    from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
    from langchain_core.runnables.history import RunnableWithMessageHistory

    history = InMemoryChatMessageHistory()
    history.add_messages([HumanMessage(f"m{i}") for i in range(30)])
    model = scripted(ai("ok"))
    prompt = ChatPromptTemplate.from_messages(
        [MessagesPlaceholder("history"), MessagesPlaceholder("input")]
    )
    chain = RunnableWithMessageHistory(
        prompt | model,
        lambda _s: history,
        input_messages_key="input",
        history_messages_key="history",
    )
    chain.invoke({"input": [HumanMessage("new")]}, config={"configurable": {"session_id": "s"}})
    assert len(model.seen[0]) == 31  # no window: all 30 stored messages and the new one


def test_measured_trim_messages_keeps_the_most_recent_that_fit_and_drops_a_message_that_is_too_big_whole():
    from lab_common.lc import window_messages

    messages = [
        HumanMessage("a" * 10),
        AIMessage("b" * 10),
        HumanMessage("c" * 10),
        AIMessage("d" * 10),
    ]
    assert [m.content[0] for m in window_messages(messages, 2, 1000)] == ["c", "d"]
    assert [m.content[0] for m in window_messages(messages, 20, 25)] == ["c", "d"]
    assert window_messages([HumanMessage("x" * 50)], 20, 25) == []


def test_measured_the_obvious_langgraph_design_stores_the_input_of_a_failed_turn():
    from langchain_core.messages import SystemMessage as System
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import END, START, MessagesState, StateGraph

    saver = InMemorySaver()

    def build(model):
        def respond(state):
            return {"messages": [model.invoke([System("s"), *state["messages"]])]}

        graph = StateGraph(MessagesState)
        graph.add_node("respond", respond)
        graph.add_edge(START, "respond")
        graph.add_edge("respond", END)
        return graph.compile(checkpointer=saver)

    config = {"configurable": {"thread_id": "t"}}
    build(scripted(ai("a1"))).invoke({"messages": [HumanMessage("q1")]}, config)
    with pytest.raises(AssertionError):
        build(scripted()).invoke({"messages": [HumanMessage("q2")]}, config)
    stored = build(scripted()).get_state(config).values["messages"]
    assert [m.content for m in stored] == [
        "q1",
        "a1",
        "q2",
    ]  # the failed turn's question was stored


def test_measured_the_saver_keeps_a_checkpoint_per_step_and_has_no_way_to_prune_them():
    from langchain_core.messages import SystemMessage as System
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import END, START, MessagesState, StateGraph

    saver = InMemorySaver()
    with pytest.raises(NotImplementedError):
        saver.prune(["t"])  # the method exists on the saver and is not implemented for it

    model = scripted(*replies(5))

    def respond(state):
        return {"messages": [model.invoke([System("s"), *state["messages"]])]}

    graph = StateGraph(MessagesState)
    graph.add_node("respond", respond)
    graph.add_edge(START, "respond")
    graph.add_edge("respond", END)
    plain = graph.compile(checkpointer=saver)
    config = {"configurable": {"thread_id": "t"}}
    for i in range(5):
        plain.invoke({"messages": [HumanMessage(f"q{i}")]}, config)
    assert len(list(saver.list(config))) == 15  # three checkpoints per turn, kept for ever


def test_our_rewrite_keeps_one_checkpoint_per_conversation_however_many_turns():
    chat, _, _ = make(LangGraphMemoryChat, MemoryLimits(), n=6)
    cid = chat.create().conversation_id
    for _ in range(5):
        ask(chat, cid)
    assert len(list(chat._saver.list({"configurable": {"thread_id": cid}}))) == 1
    assert len(chat.get(cid).messages) == 10


def test_measured_langchains_own_message_history_classes_are_deprecated_in_favour_of_langgraph_persistence():
    # LangChain warns once per process, so this runs in a fresh interpreter
    import subprocess
    import sys

    code = (
        "import warnings; warnings.simplefilter('always')\n"
        "from langchain_core.chat_history import InMemoryChatMessageHistory\n"
        "from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder\n"
        "from langchain_core.runnables.history import RunnableWithMessageHistory\n"
        "h = InMemoryChatMessageHistory()\n"
        "p = ChatPromptTemplate.from_messages([MessagesPlaceholder('history'), MessagesPlaceholder('input')])\n"
        "RunnableWithMessageHistory(p, lambda s: h, input_messages_key='input', history_messages_key='history')\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    ).stderr
    assert "InMemoryChatMessageHistory" in out and "deprecated" in out
    assert "RunnableWithMessageHistory is deprecated" in out and "LangGraph" in out
