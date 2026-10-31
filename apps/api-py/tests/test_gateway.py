"""The model gateway: chain building, and what happens on 429s, timeouts and server errors.

Calls go to a scripted fake provider registered with LiteLLM, so every outcome is exact and no
network, key or model is involved."""

import asyncio
import io
import json
import time

import litellm
import pytest
import structlog
from litellm import CustomLLM, ModelResponse

from app.config import get_settings
from app.llm import gateway
from app.llm.gateway import LlmUnavailableError, Plan, Route
from app.logs import configure_logging

REAL_SLEEP = asyncio.sleep  # the `waits` fixture replaces asyncio.sleep; keep the real one


class Scripted(CustomLLM):
    """Replays a script of outcomes per model: an exception is raised, a string is returned."""

    script: dict[str, list] = {}
    calls: list[str] = []

    async def acompletion(self, model, messages, **kwargs):
        Scripted.calls.append(model)
        outcome = Scripted.script[model].pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return ModelResponse(
            model=model,
            choices=[
                {
                    "message": {"role": "assistant", "content": outcome},
                    "index": 0,
                    "finish_reason": "stop",
                }
            ],
            usage={"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
        )


def rate_limit(model: str) -> Exception:
    return litellm.RateLimitError(message="429 slow down", llm_provider="scripted", model=model)


def server_error(model: str) -> Exception:
    return litellm.InternalServerError(message="500", llm_provider="scripted", model=model)


def timeout(model: str) -> Exception:
    return litellm.Timeout(message="timed out", model=model, llm_provider="scripted")


@pytest.fixture(autouse=True)
def scripted_provider(monkeypatch):
    monkeypatch.setattr(
        litellm, "custom_provider_map", [{"provider": "scripted", "custom_handler": Scripted()}]
    )
    monkeypatch.setenv("LLM_MAX_RETRIES", "2")
    monkeypatch.setenv("LLM_RETRY_MIN_SECONDS", "0")
    monkeypatch.setenv("LLM_COOLDOWN_SECONDS", "30")
    Scripted.script, Scripted.calls = {}, []
    gateway._router.cache_clear()
    yield
    gateway._router.cache_clear()


@pytest.fixture
def waits(monkeypatch):
    """Records every wait the retry loop asks for, without actually waiting."""
    requested: list[float] = []
    real_sleep = asyncio.sleep

    async def fake_sleep(delay, *args, **kwargs):
        requested.append(delay)
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    return requested


def use_models(monkeypatch, script: dict[str, list]) -> None:
    """Script the outcomes and make the chain be exactly these models, first to last."""
    Scripted.script = {name: list(outcomes) for name, outcomes in script.items()}
    routes = tuple(
        Route("cloud", name, f"scripted/{name}", api_key="SECRET-ROUTE-KEY") for name in script
    )
    first = next(iter(script))
    monkeypatch.setattr(
        gateway, "build_chain", lambda provider, model=None: Plan(routes, "cloud", first)
    )


async def ask() -> object:
    return await gateway.generate("be brief", [{"role": "user", "content": "hi"}], "cloud")


# ---------------------------------------------------------------- chain building


def test_the_default_cloud_chain_is_the_default_then_the_fallback_chain_then_local(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    plan = gateway.build_chain("cloud")
    names = [r.model for r in plan.chain]
    assert names[0] == "liquid/lfm-2.5-2.6b:free"
    assert names[1:4] == [
        "google/gemma-4-31b-it:free",
        "google/gemma-4-26b-a4b-it:free",
        "poolside/laguna-xs-2.1:free",
    ]
    assert plan.chain[-1].provider == "ollama"
    assert [r.litellm_model for r in plan.chain[:2]] == [
        "openrouter/liquid/lfm-2.5-2.6b:free",
        "openrouter/google/gemma-4-31b-it:free",
    ]
    assert (plan.requested_provider, plan.requested_model) == ("cloud", "liquid/lfm-2.5-2.6b:free")


def test_a_chosen_model_goes_first_and_is_not_repeated(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    names = [r.model for r in gateway.build_chain("cloud", "google/gemma-4-26b-a4b-it:free").chain]
    assert names[0] == "google/gemma-4-26b-a4b-it:free"
    assert names.count("google/gemma-4-26b-a4b-it:free") == 1
    assert (
        "liquid/lfm-2.5-2.6b:free" not in names[1:3] or names.count("liquid/lfm-2.5-2.6b:free") == 1
    )


def test_local_first_then_cloud_when_a_key_exists(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    chain = gateway.build_chain("ollama").chain
    assert chain[0].provider == "ollama" and chain[1].provider == "cloud"


def test_without_a_key_only_the_local_model_is_available(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    plan = gateway.build_chain("cloud")
    assert [r.provider for r in plan.chain] == ["ollama"]
    assert plan.requested_provider == "cloud"  # so the answer is flagged as a fallback


def test_the_missing_key_warning_appears_only_when_the_cloud_was_requested(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    stream = io.StringIO()
    configure_logging("INFO", "json", stream)
    try:
        gateway.build_chain("ollama")
        assert stream.getvalue() == ""
        gateway.build_chain("cloud")
    finally:
        configure_logging("INFO", "json")
    assert "openrouter_key_missing" in stream.getvalue()


def test_an_unknown_provider_is_rejected():
    with pytest.raises(ValueError, match="Unknown LLM provider"):
        gateway.build_chain("openrouter")


def test_a_route_never_prints_its_key():
    assert "SECRET" not in repr(Route("cloud", "m", "openrouter/m", api_key="SECRET-KEY"))


# ------------------------------------------------------------------- the calls


@pytest.mark.asyncio
async def test_a_healthy_first_model_answers_with_no_fallback(monkeypatch):
    use_models(monkeypatch, {"a:free": ["hello"], "b:free": ["never used"]})
    result = await ask()
    assert result.content == "hello" and result.model == "a:free" and result.provider == "cloud"
    assert (result.tokens_in, result.tokens_out) == (11, 7)
    assert result.estimated_cost == 0.0 and result.latency_ms >= 0
    assert result.fallback_used is False and result.fallback_from is None
    assert Scripted.calls == ["a:free"]


@pytest.mark.asyncio
async def test_a_429_falls_back_to_the_next_model(monkeypatch, waits):
    """The sub-stage 1.2 exit criterion."""
    use_models(monkeypatch, {"a:free": [rate_limit("a:free")], "b:free": ["from b"]})
    result = await ask()
    assert result.content == "from b" and result.model == "b:free"
    assert result.fallback_used is True
    assert (result.fallback_from, result.fallback_from_model) == ("cloud", "a:free")
    assert Scripted.calls == ["a:free", "b:free"]


@pytest.mark.asyncio
async def test_a_429_is_not_retried_on_the_same_model(monkeypatch, waits):
    use_models(monkeypatch, {"a:free": [rate_limit("a:free")], "b:free": ["ok"]})
    await ask()
    assert Scripted.calls.count("a:free") == 1
    assert waits == []


@pytest.mark.asyncio
async def test_a_server_error_is_retried_on_the_same_model_then_succeeds(monkeypatch, waits):
    use_models(
        monkeypatch, {"a:free": [server_error("a:free"), "second try"], "b:free": ["unused"]}
    )
    result = await ask()
    assert result.content == "second try" and result.model == "a:free" and not result.fallback_used
    assert Scripted.calls == ["a:free", "a:free"]
    assert len(waits) == 1


@pytest.mark.asyncio
async def test_a_timeout_is_retried_too(monkeypatch, waits):
    use_models(monkeypatch, {"a:free": [timeout("a:free"), "after timeout"]})
    assert (await ask()).content == "after timeout"


@pytest.mark.asyncio
async def test_waits_between_retries_grow_and_stop_after_the_limit_then_fall_back(
    monkeypatch, waits
):
    use_models(monkeypatch, {"a:free": [server_error("a:free")] * 3, "b:free": ["from b"]})
    result = await ask()
    assert Scripted.calls == [
        "a:free",
        "a:free",
        "a:free",
        "b:free",
    ]  # 1 try + 2 retries, then next model
    assert result.model == "b:free" and result.fallback_used
    assert len(waits) >= 2 and waits == sorted(waits), (
        "one wait per retry, each longer than the last"
    )


@pytest.mark.asyncio
async def test_models_are_tried_in_order_until_one_answers(monkeypatch, waits):
    use_models(
        monkeypatch,
        {"a:free": [rate_limit("a:free")], "b:free": [rate_limit("b:free")], "c:free": ["from c"]},
    )
    result = await ask()
    assert Scripted.calls == ["a:free", "b:free", "c:free"] and result.model == "c:free"


@pytest.mark.asyncio
async def test_when_every_model_fails_the_error_names_them_and_leaks_nothing(monkeypatch, waits):
    use_models(monkeypatch, {"a:free": [rate_limit("a:free")], "b:free": [rate_limit("b:free")]})
    with pytest.raises(LlmUnavailableError) as caught:
        await ask()
    message = str(caught.value)
    assert "a:free" in message and "b:free" in message and "RateLimitError" in message
    assert "SECRET" not in message


@pytest.mark.asyncio
async def test_an_empty_answer_is_an_error_not_a_blank_reply(monkeypatch):
    use_models(monkeypatch, {"a:free": [""]})
    with pytest.raises(LlmUnavailableError, match="empty response"):
        await ask()


@pytest.mark.asyncio
async def test_a_model_that_just_failed_is_skipped_on_the_next_request(monkeypatch, waits):
    use_models(monkeypatch, {"a:free": [rate_limit("a:free"), "a is back"], "b:free": ["b1", "b2"]})
    await ask()
    Scripted.calls.clear()
    second = await ask()
    assert Scripted.calls == ["b:free"], "cool-down: no new call to the model that just failed"
    assert second.content == "b2" and second.fallback_used


# ----------------------------------------------------------------- small pieces


class FakeResponse:
    def __init__(self, hidden):
        self._hidden_params = hidden


@pytest.mark.parametrize(
    ("hidden", "expected"),
    [
        ({"additional_headers": {"x-litellm-model-group": "r2"}}, 2),
        ({"additional_headers": {}}, 0),
        ({}, 0),
        ({"additional_headers": {"x-litellm-model-group": "weird"}}, 0),
        ({"additional_headers": {"x-litellm-model-group": "r9"}}, 0),
    ],
)
def test_the_answering_model_is_read_from_the_response(hidden, expected):
    assert gateway._answering_index(FakeResponse(hidden), 3) == expected


@pytest.mark.asyncio
async def test_failed_attempts_are_logged_with_the_request_id_and_without_secrets(
    monkeypatch, waits
):
    stream = io.StringIO()
    configure_logging("INFO", "json", stream)
    structlog.contextvars.bind_contextvars(request_id="req-123")
    try:
        use_models(monkeypatch, {"a:free": [rate_limit("a:free")], "b:free": ["ok"]})
        await ask()
        # LiteLLM logs failures from a background task: wait for it, up to a deadline, not a fixed time
        deadline = time.monotonic() + 5
        while "llm_attempt_failed" not in stream.getvalue() and time.monotonic() < deadline:
            await REAL_SLEEP(0.02)
    finally:
        structlog.contextvars.clear_contextvars()
        configure_logging("INFO", "json")
    records = [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]
    failed = [r for r in records if r["event"] == "llm_attempt_failed"]
    assert failed and failed[0]["error"] == "RateLimitError" and failed[0]["status"] == 429
    assert failed[0]["request_id"] == "req-123"
    assert any(r["event"] == "llm_fallback_used" and r["answered"] == "b:free" for r in records)
    assert "SECRET" not in stream.getvalue() and "hi" not in {r.get("content") for r in records}


def test_gateway_settings_have_sensible_defaults(monkeypatch):
    for name in (
        "LLM_MAX_RETRIES",
        "LLM_RETRY_MIN_SECONDS",
        "LLM_COOLDOWN_SECONDS",
        "LLM_TIMEOUT_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)
    s = get_settings()
    assert (
        s.llm_timeout_seconds,
        s.llm_max_retries,
        s.llm_retry_min_seconds,
        s.llm_cooldown_seconds,
    ) == (60.0, 2, 1, 30.0)
