"""LLM provider gateway — the only module that talks to LLM providers.

One interface across OpenAI / Anthropic / Ollama via LiteLLM, with
structured output, validation retries, and per-call cost logging.
Model choice is always a parameter (default from CASINOAI_DEFAULT_MODEL);
comparing models is part of the experiment design, so never hardcode one.
"""

import base64
import json
import os
import time
from pathlib import Path
from typing import Any

import litellm
from pydantic import BaseModel, ValidationError

litellm.suppress_debug_info = True
litellm.drop_params = True  # ignore params a provider doesn't support

DEFAULT_COST_LOG = Path("data/llm_calls.jsonl")


class LLMError(Exception):
    """The provider call failed, or output never validated against the schema."""


class LLMResponse(BaseModel):
    model: str
    text: str
    parsed: Any = None  # schema instance when a schema was requested
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_s: float = 0.0
    attempts: int = 1


def resolve_model(model: str | None) -> str:
    resolved = model or os.environ.get("CASINOAI_DEFAULT_MODEL")
    if not resolved:
        raise LLMError("No model given and CASINOAI_DEFAULT_MODEL is not set")
    return resolved


def _route(model: str) -> tuple[str, dict[str, Any]]:
    """Map a casinoai model id to the litellm model id + provider kwargs.

    - ollama/<m>        → local Ollama server (OLLAMA_BASE_URL)
    - ollama-cloud/<m>  → ollama.com hosted models (flat-rate subscription) via
                          their OpenAI-compatible endpoint; needs OLLAMA_API_KEY
    - anything else     → passed to litellm unchanged
    """
    if model.startswith("ollama-cloud/"):
        api_key = os.environ.get("OLLAMA_API_KEY")
        if not api_key:
            raise LLMError(
                "ollama-cloud/ models need OLLAMA_API_KEY (create one at ollama.com/settings/keys)"
            )
        return (
            "openai/" + model.removeprefix("ollama-cloud/"),
            {
                "api_base": os.environ.get("OLLAMA_CLOUD_BASE_URL", "https://ollama.com/v1"),
                "api_key": api_key,
            },
        )
    if model.startswith("ollama/"):
        return model, {"api_base": os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")}
    return model, {}


def _response_format(schema: type[BaseModel]) -> dict[str, Any]:
    """JSON-schema response_format compatible across providers. OpenAI's
    structured-output endpoint rejects `oneOf`/`discriminator` (Pydantic emits
    them for discriminated unions), so rewrite to `anyOf`. We validate the
    output with Pydantic ourselves, so strict mode is unnecessary."""

    def fix(node: Any) -> None:
        if isinstance(node, dict):
            if "oneOf" in node:
                node["anyOf"] = node.pop("oneOf")
            node.pop("discriminator", None)
            for value in node.values():
                fix(value)
        elif isinstance(node, list):
            for value in node:
                fix(value)

    json_schema = schema.model_json_schema()
    fix(json_schema)
    return {
        "type": "json_schema",
        "json_schema": {"name": schema.__name__, "schema": json_schema, "strict": False},
    }


def _strip_to_json(text: str) -> str:
    """Best-effort recovery of a JSON body from model output. Some providers
    (e.g. ollama.com's OpenAI-compat endpoint) don't strictly enforce
    response_format, and models wrap JSON in ```json fences or prose."""
    text = text.strip()
    if text.startswith("```"):
        first_newline = text.find("\n")
        closing = text.rfind("```")
        if first_newline != -1 and closing > first_newline:
            return text[first_newline + 1 : closing].strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        return text[start : end + 1]
    return text


def _image_part(image: str | Path | bytes) -> dict[str, Any]:
    """One multimodal image part. Accepts raw PNG bytes or a path to an image;
    always sent inline as a data URL so no provider needs network access to it."""
    if isinstance(image, bytes | bytearray):
        raw, suffix = bytes(image), ".png"
    else:
        p = Path(image)
        raw, suffix = p.read_bytes(), p.suffix.lower()
    mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}.get(
        suffix, "image/png"
    )
    b64 = base64.b64encode(raw).decode()
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}


def _log_call(record: dict[str, Any], log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a") as f:
        f.write(json.dumps(record) + "\n")


def complete(
    prompt: str,
    *,
    model: str | None = None,
    schema: type[BaseModel] | None = None,
    system: str | None = None,
    temperature: float = 0.0,
    max_tokens: int | None = None,
    max_retries: int = 2,
    tag: str | None = None,
    images: list[str | Path | bytes] | None = None,
    cost_log: Path = DEFAULT_COST_LOG,
) -> LLMResponse:
    """Run one completion; validate against `schema` if given, retrying with
    the validation error fed back to the model. Every call (including failed
    validation attempts) is appended to the cost log.

    `images` sends a multimodal (vision) request — the prompt plus each image
    inlined as a data URL. The model must be vision-capable."""
    resolved = resolve_model(model)
    litellm_model, provider_kwargs = _route(resolved)
    messages: list[dict[str, str]] = []
    if schema is not None:
        # Belt and braces: some endpoints (e.g. ollama.com) treat
        # response_format as advisory, so spell the schema out in-prompt too.
        schema_msg = (
            "Your entire reply must be a single JSON object that validates against "
            "this JSON Schema — use the exact property names and discriminator "
            "values shown; no markdown fences, no commentary:\n"
            + json.dumps(_response_format(schema)["json_schema"]["schema"])
        )
        system = f"{system}\n\n{schema_msg}" if system else schema_msg
    if system:
        messages.append({"role": "system", "content": system})
    if images:
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        content.extend(_image_part(img) for img in images)
        messages.append({"role": "user", "content": content})
    else:
        messages.append({"role": "user", "content": prompt})

    total_in = total_out = 0
    total_cost = 0.0
    start = time.monotonic()
    last_error: Exception | None = None

    for attempt in range(1, max_retries + 2):
        try:
            response = litellm.completion(
                model=litellm_model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format=_response_format(schema) if schema else None,
                **provider_kwargs,
            )
        except Exception as exc:
            raise LLMError(f"{resolved} call failed: {exc}") from exc

        text = response.choices[0].message.content or ""
        usage = getattr(response, "usage", None)
        in_tok = getattr(usage, "prompt_tokens", 0) or 0
        out_tok = getattr(usage, "completion_tokens", 0) or 0
        try:
            cost = litellm.completion_cost(completion_response=response)
        except Exception:
            cost = 0.0  # local models have no price entry
        total_in += in_tok
        total_out += out_tok
        total_cost += cost
        _log_call(
            {
                "ts": time.time(),
                "model": resolved,
                "tag": tag,
                "attempt": attempt,
                "input_tokens": in_tok,
                "output_tokens": out_tok,
                "cost_usd": cost,
                "schema": schema.__name__ if schema else None,
            },
            cost_log,
        )

        parsed = None
        if schema is not None:
            try:
                parsed = schema.model_validate_json(_strip_to_json(text))
            except ValidationError as exc:
                last_error = exc
                messages.append({"role": "assistant", "content": text})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Your previous reply did not validate against the required "
                            f"JSON schema:\n{exc}\nRespond again with ONLY valid JSON."
                        ),
                    }
                )
                continue

        return LLMResponse(
            model=resolved,
            text=text,
            parsed=parsed,
            input_tokens=total_in,
            output_tokens=total_out,
            cost_usd=total_cost,
            latency_s=time.monotonic() - start,
            attempts=attempt,
        )

    raise LLMError(
        f"{resolved} output failed schema validation after {max_retries + 1} attempts: {last_error}"
    )
