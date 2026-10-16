"""Model factory: one env var switches between Groq, OpenAI, or any OpenAI-compatible server.

LLM_MODEL uses the "provider:model" format:
    openai:gpt-4.1-mini              -> OpenAI
    groq:openai/gpt-oss-120b         -> Groq
    openai:<model> + LLM_BASE_URL    -> any OpenAI-compatible API (Ollama, vLLM, OpenRouter...)
"""

from __future__ import annotations

import os

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

DEFAULT_MODEL = "openai:gpt-4.1-mini"

KEY_ENV = {"groq": "GROQ_API_KEY", "openai": "OPENAI_API_KEY"}


def model_spec() -> str:
    return os.getenv("LLM_MODEL", DEFAULT_MODEL)


def build_model(spec: str | None = None) -> BaseChatModel:
    spec = spec or model_spec()
    if ":" not in spec:
        raise ValueError(f"LLM_MODEL must look like 'provider:model', got {spec!r}")
    provider, name = spec.split(":", 1)
    provider = provider.lower()
    if provider not in KEY_ENV:
        raise ValueError(f"Unsupported provider {provider!r}. Use 'groq' or 'openai'.")

    kwargs: dict = {"max_retries": 2, "timeout": 60}
    if os.getenv("LLM_TEMPERATURE"):  # leave unset for reasoning models (e.g. gpt-5 family)
        kwargs["temperature"] = float(os.environ["LLM_TEMPERATURE"])

    base_url = os.getenv("LLM_BASE_URL")
    if provider == "openai" and base_url:
        kwargs["base_url"] = base_url
        kwargs["api_key"] = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or "not-needed"
    elif not os.getenv(KEY_ENV[provider]):
        raise RuntimeError(f"{KEY_ENV[provider]} is not set (needed for {spec}). See .env.example.")

    return init_chat_model(name, model_provider=provider, **kwargs)
