"""Live provider smoke tests — the Phase 1 exit criteria.

Same schema-constrained prompt through every configured provider.
Marked `llm`, so skipped by default; run with: uv run pytest -m llm
Providers without credentials (or an unreachable Ollama) are skipped,
not failed, so the suite degrades gracefully per environment.
"""

import os
import urllib.error
import urllib.request

import pytest
from pydantic import BaseModel

from casinoai.llm import complete

pytestmark = pytest.mark.llm

PROMPT = "What is 17 + 25? Reply as JSON with fields `answer` (int) and `reasoning` (string)."


class MathAnswer(BaseModel):
    answer: int
    reasoning: str


def _ollama_up() -> bool:
    url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    try:
        with urllib.request.urlopen(f"{url}/api/tags", timeout=3):
            return True
    except (urllib.error.URLError, OSError):
        return False


PROVIDERS = [
    pytest.param(
        "ollama/llama3.1:8b",
        marks=pytest.mark.skipif(not _ollama_up(), reason="Ollama server not running"),
    ),
    pytest.param(
        "openai/gpt-5-mini",
        marks=pytest.mark.skipif(not os.environ.get("OPENAI_API_KEY"), reason="no OPENAI_API_KEY"),
    ),
    pytest.param(
        "anthropic/claude-haiku-4-5",
        marks=pytest.mark.skipif(
            not os.environ.get("ANTHROPIC_API_KEY"), reason="no ANTHROPIC_API_KEY"
        ),
    ),
    pytest.param(
        "ollama-cloud/kimi-k2.6:cloud",
        marks=pytest.mark.skipif(not os.environ.get("OLLAMA_API_KEY"), reason="no OLLAMA_API_KEY"),
    ),
]


@pytest.mark.parametrize("model", PROVIDERS)
def test_structured_completion(model):
    r = complete(PROMPT, model=model, schema=MathAnswer, tag="smoke")
    assert isinstance(r.parsed, MathAnswer)
    assert r.parsed.answer == 42
    assert r.output_tokens > 0
