"""The LLM call: an async OpenAI-compatible client (LM Studio) that returns JSON matching a schema.

Every node that needs the model asks for **structured output** (`response_format: json_schema`, which LM Studio
enforces with a grammar), so the graph reads fields, not prose. Anything the model returns is still checked in code
by the caller: the schema says what shape is allowed, the node decides what is true.
"""
import asyncio
import json
import logging
import time
import weakref
from dataclasses import dataclass

from openai import AsyncOpenAI

from copilot import config, observability

log = logging.getLogger("copilot.llm")


class LLMError(Exception):
    """The model could not be reached or did not return JSON of the requested shape."""


@dataclass
class LLMResult:
    data: dict
    raw: str
    ms: int
    tokens_in: int | None
    tokens_out: int | None


# One client per event loop: an httpx connection pool must not be shared across loops (tests start new loops).
_clients: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, tuple[str, AsyncOpenAI]]" = (
    weakref.WeakKeyDictionary())


def _client() -> AsyncOpenAI:
    loop = asyncio.get_running_loop()
    cached = _clients.get(loop)
    if cached is None or cached[0] != config.LLM_BASE_URL:  # the base URL can change in tests
        cached = (config.LLM_BASE_URL, AsyncOpenAI(base_url=config.LLM_BASE_URL, api_key="lm-studio",
                                                   timeout=config.LLM_TIMEOUT_SECONDS, max_retries=0))
        _clients[loop] = cached
    return cached[1]


def parse_json(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):  # tolerate a markdown fence if a model adds one anyway
        text = text.strip("`").removeprefix("json").strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMError(f"the model did not return JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise LLMError("the model returned JSON that is not an object")
    return data


async def complete_json(system: str, user: str, schema: dict, name: str, max_tokens: int = 1500) -> LLMResult:
    """One chat completion that must return a JSON object matching `schema`."""
    extra = {"reasoning_effort": config.LLM_REASONING_EFFORT} if config.LLM_REASONING_EFFORT else {}
    start = time.perf_counter()
    try:
        response = await _client().chat.completions.create(
            model=config.LLM_MODEL,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0,
            max_tokens=max_tokens,
            response_format={"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": schema}},
            **extra,
        )
    except Exception as exc:  # connection refused, timeout, HTTP 500 ...: one friendly error for the graph
        raise LLMError(f"the model request failed ({type(exc).__name__})") from exc
    ms = int((time.perf_counter() - start) * 1000)
    raw = response.choices[0].message.content or ""
    usage = response.usage
    log.info("llm %s: %d ms, %s -> %s tokens", name, ms, usage.prompt_tokens if usage else "?",
             usage.completion_tokens if usage else "?")
    observability.add_tokens(usage.prompt_tokens if usage else None, usage.completion_tokens if usage else None)
    return LLMResult(data=parse_json(raw), raw=raw, ms=ms, tokens_in=usage.prompt_tokens if usage else None,
                     tokens_out=usage.completion_tokens if usage else None)
