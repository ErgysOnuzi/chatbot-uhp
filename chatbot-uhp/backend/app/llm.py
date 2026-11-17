"""Klienti për modelin gjuhësor.

DeepSeek dhe Ollama kanë të dyja API të përputhshme me OpenAI, prandaj i njëjti kod
punon për të dyja. Për të ndërruar modelin ndryshohen vetëm LLM_BASE_URL, LLM_API_KEY
dhe LLM_MODEL në .env.
"""

from collections.abc import Iterator
from functools import lru_cache

from openai import OpenAI

from .config import settings


@lru_cache(maxsize=1)
def _client() -> OpenAI:
    return OpenAI(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key or "pa-celes",  # Ollama nuk kërkon çelës
        timeout=90,
    )


def stream_chat(messages: list[dict]) -> Iterator[str]:
    stream = _client().chat.completions.create(
        model=settings.llm_model,
        messages=messages,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
        stream=True,
    )
    for event in stream:
        if event.choices and event.choices[0].delta.content:
            yield event.choices[0].delta.content
