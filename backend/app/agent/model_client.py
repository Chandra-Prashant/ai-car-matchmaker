"""Model client — provider-agnostic access to a tool-calling LLM.

Everything here speaks the OpenAI chat-completions shape, which Gemini,
Ollama, Groq, OpenRouter and OpenAI itself all serve. Choosing a provider is
an environment variable, not a code change.

WHY NOT A FRAMEWORK
-------------------
The hard parts of this agent — phase guards, tool scoping, deterministic
transitions — live in `phases.py` and `tools.py` and are already testable
without a model. What remains is a tool-use loop, which is short enough that
a framework would add indirection without removing work, and would make the
orchestration harder to explain rather than easier.

FREE-TIER CONSIDERATIONS
------------------------
Free tiers cap requests per day far more tightly than tokens. Two
consequences shape this module: rounds per turn are capped so a confused
agent cannot burn quota in a loop, and 429s retry with backoff so hitting a
limit mid-demo becomes a pause rather than a failure.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any

from openai import APIStatusError, AsyncOpenAI

#: Base URLs for providers that serve an OpenAI-compatible endpoint.
PROVIDER_BASE_URLS = {
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "ollama": "http://localhost:11434/v1",
    "groq": "https://api.groq.com/openai/v1",
    "openai": None,  # the client's own default
}

PROVIDER_KEY_VARS = {
    "gemini": "GEMINI_API_KEY",
    "ollama": None,  # local, unauthenticated
    "groq": "GROQ_API_KEY",
    "openai": "OPENAI_API_KEY",
}

DEFAULT_MODELS = {
    "gemini": "gemini-2.5-flash",
    "ollama": "qwen3:4b",
    "groq": "llama-3.3-70b-versatile",
    "openai": "gpt-4o-mini",
}


@dataclass(frozen=True)
class ModelConfig:
    provider: str
    model: str
    base_url: str | None
    api_key: str
    max_tokens: int = 2048
    temperature: float = 0.3
    #: Ceiling on tool-call rounds within a single turn.
    max_rounds: int = 8
    #: Retries on 429 or transient 5xx.
    max_retries: int = 4

    @classmethod
    def from_env(cls) -> ModelConfig:
        provider = os.getenv("LLM_PROVIDER", "gemini").lower()
        if provider not in PROVIDER_BASE_URLS:
            raise ValueError(
                f"Unknown LLM_PROVIDER {provider!r}. "
                f"Available: {', '.join(sorted(PROVIDER_BASE_URLS))}"
            )

        key_var = PROVIDER_KEY_VARS[provider]
        api_key = os.getenv(key_var, "") if key_var else "local"
        if key_var and not api_key:
            raise ValueError(
                f"{key_var} is not set. Add it to .env — see .env.example."
            )

        return cls(
            provider=provider,
            model=os.getenv("LLM_MODEL") or DEFAULT_MODELS[provider],
            base_url=PROVIDER_BASE_URLS[provider],
            api_key=api_key,
            max_rounds=int(os.getenv("LLM_MAX_ROUNDS", "8")),
        )


class RateLimited(Exception):
    """Retries exhausted against a rate limit.

    Distinct from a generic failure so the runner can tell the user to wait
    rather than implying something is broken.
    """


class ModelClient:
    """Thin async wrapper over an OpenAI-compatible chat endpoint."""

    def __init__(self, config: ModelConfig | None = None) -> None:
        self.config = config or ModelConfig.from_env()
        kwargs: dict[str, Any] = {"api_key": self.config.api_key}
        if self.config.base_url:
            kwargs["base_url"] = self.config.base_url
        self._client = AsyncOpenAI(**kwargs)

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> Any:
        """One completion, retrying rate limits with exponential backoff."""
        delay = 1.0
        last_error: Exception | None = None

        for attempt in range(self.config.max_retries):
            try:
                kwargs: dict[str, Any] = {
                    "model": self.config.model,
                    "messages": messages,
                    "max_tokens": self.config.max_tokens,
                    "temperature": self.config.temperature,
                }
                if tools:
                    kwargs["tools"] = tools
                    kwargs["tool_choice"] = "auto"

                response = await self._client.chat.completions.create(**kwargs)
                return response.choices[0].message

            except APIStatusError as exc:
                last_error = exc
                retryable = exc.status_code == 429 or exc.status_code >= 500
                if not retryable or attempt == self.config.max_retries - 1:
                    break
                await asyncio.sleep(delay)
                delay *= 2

        if isinstance(last_error, APIStatusError) and last_error.status_code == 429:
            raise RateLimited(
                "The model provider is rate limiting. On a free tier this "
                "usually means the daily or per-minute quota is spent — wait "
                "a moment and try again."
            ) from last_error

        raise last_error if last_error else RuntimeError("Completion failed")

    def describe(self) -> str:
        return f"{self.config.provider}/{self.config.model}"
