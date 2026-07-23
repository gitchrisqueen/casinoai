"""Unit tests for the LLM gateway — no live provider calls (litellm is mocked)."""

import json
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from casinoai.llm import LLMError, complete, gateway


class Verdict(BaseModel):
    answer: int
    reasoning: str


def fake_response(content: str):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
    )


@pytest.fixture
def cost_log(tmp_path):
    return tmp_path / "calls.jsonl"


def test_plain_completion(monkeypatch, cost_log):
    monkeypatch.setattr(gateway.litellm, "completion", lambda **kw: fake_response("hi"))
    monkeypatch.setattr(gateway.litellm, "completion_cost", lambda **kw: 0.001)
    r = complete("hello", model="openai/test", cost_log=cost_log)
    assert r.text == "hi"
    assert r.cost_usd == 0.001
    assert r.attempts == 1


def test_schema_validation_and_parse(monkeypatch, cost_log):
    body = json.dumps({"answer": 42, "reasoning": "math"})
    monkeypatch.setattr(gateway.litellm, "completion", lambda **kw: fake_response(body))
    monkeypatch.setattr(gateway.litellm, "completion_cost", lambda **kw: 0.0)
    r = complete("q", model="openai/test", schema=Verdict, cost_log=cost_log)
    assert isinstance(r.parsed, Verdict)
    assert r.parsed.answer == 42


def test_validation_retry_then_success(monkeypatch, cost_log):
    replies = iter(["not json", json.dumps({"answer": 1, "reasoning": "r"})])
    monkeypatch.setattr(gateway.litellm, "completion", lambda **kw: fake_response(next(replies)))
    monkeypatch.setattr(gateway.litellm, "completion_cost", lambda **kw: 0.0)
    r = complete("q", model="openai/test", schema=Verdict, cost_log=cost_log)
    assert r.attempts == 2
    assert r.parsed.answer == 1
    # both attempts were cost-logged
    assert len(cost_log.read_text().strip().splitlines()) == 2


def test_validation_exhausts_retries(monkeypatch, cost_log):
    monkeypatch.setattr(gateway.litellm, "completion", lambda **kw: fake_response("junk"))
    monkeypatch.setattr(gateway.litellm, "completion_cost", lambda **kw: 0.0)
    with pytest.raises(LLMError, match="schema validation"):
        complete("q", model="openai/test", schema=Verdict, max_retries=1, cost_log=cost_log)


def test_missing_model_raises(monkeypatch, cost_log):
    monkeypatch.delenv("CASINOAI_DEFAULT_MODEL", raising=False)
    with pytest.raises(LLMError, match="CASINOAI_DEFAULT_MODEL"):
        complete("q", cost_log=cost_log)


def test_ollama_gets_api_base(monkeypatch, cost_log):
    seen = {}

    def capture(**kw):
        seen.update(kw)
        return fake_response("ok")

    monkeypatch.setattr(gateway.litellm, "completion", capture)
    monkeypatch.setattr(gateway.litellm, "completion_cost", lambda **kw: 0.0)
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://elsewhere:1234")
    complete("q", model="ollama/foo", cost_log=cost_log)
    assert seen["api_base"] == "http://elsewhere:1234"
    assert seen["model"] == "ollama/foo"


def test_ollama_cloud_routes_to_openai_compat(monkeypatch, cost_log):
    seen = {}

    def capture(**kw):
        seen.update(kw)
        return fake_response("ok")

    monkeypatch.setattr(gateway.litellm, "completion", capture)
    monkeypatch.setattr(gateway.litellm, "completion_cost", lambda **kw: 0.0)
    monkeypatch.setenv("OLLAMA_API_KEY", "test-key")
    r = complete("q", model="ollama-cloud/kimi-k2.6:cloud", cost_log=cost_log)
    assert seen["model"] == "openai/kimi-k2.6:cloud"
    assert seen["api_base"] == "https://ollama.com/v1"
    assert seen["api_key"] == "test-key"
    # response reports the casinoai model id, not the litellm routing id
    assert r.model == "ollama-cloud/kimi-k2.6:cloud"


def test_ollama_cloud_without_key_raises(monkeypatch, cost_log):
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    with pytest.raises(LLMError, match="OLLAMA_API_KEY"):
        complete("q", model="ollama-cloud/kimi-k2.6:cloud", cost_log=cost_log)


@pytest.mark.parametrize(
    "wrapped",
    [
        '```json\n{"answer": 7, "reasoning": "r"}\n```',
        '```\n{"answer": 7, "reasoning": "r"}\n```',
        'Here is the JSON:\n{"answer": 7, "reasoning": "r"}\nHope that helps!',
        '{"answer": 7, "reasoning": "r"}',
    ],
)
def test_schema_parses_despite_fences_and_prose(monkeypatch, cost_log, wrapped):
    monkeypatch.setattr(gateway.litellm, "completion", lambda **kw: fake_response(wrapped))
    monkeypatch.setattr(gateway.litellm, "completion_cost", lambda **kw: 0.0)
    r = complete("q", model="openai/test", schema=Verdict, cost_log=cost_log)
    assert r.attempts == 1
    assert r.parsed.answer == 7
