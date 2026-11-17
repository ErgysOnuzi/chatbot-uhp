"""Klienti për modelin gjuhësor.

DeepSeek dhe Ollama kanë të dyja API të përputhshme me OpenAI, prandaj i njëjti kod
punon për të dyja. Për të ndërruar modelin ndryshohen vetëm LLM_BASE_URL, LLM_API_KEY
dhe LLM_MODEL në .env.

Disa modele (p.sh. modelet "reasoning") e dërgojnë së pari arsyetimin në fushën
`reasoning_content` dhe vetëm pastaj përgjigjen në `content`. Arsyetimi nuk i shfaqet
studentit. Nëse modeli nuk kthen asnjë tekst në `content`, ngrihet EmptyAnswerError me
arsyen (p.sh. finish_reason="length" kur arsyetimi i harxhon të gjithë tokenët).
"""

import logging
from collections.abc import Iterator
from functools import lru_cache

from openai import OpenAI

from .config import settings

logger = logging.getLogger(__name__)


class EmptyAnswerError(RuntimeError):
    """Modeli përfundoi pa kthyer tekst për studentin."""


@lru_cache(maxsize=1)
def _client() -> OpenAI:
    return OpenAI(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key or "pa-celes",  # Ollama nuk kërkon çelës
        timeout=120,
    )


def stream_chat(messages: list[dict]) -> Iterator[str]:
    stream = _client().chat.completions.create(
        model=settings.llm_model,
        messages=messages,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
        stream=True,
    )
    content_chars = 0
    reasoning_chars = 0
    finish_reason = None
    for event in stream:
        if not event.choices:
            continue
        choice = event.choices[0]
        delta = choice.delta
        reasoning = getattr(delta, "reasoning_content", None) or getattr(delta, "reasoning", None)
        if reasoning:
            reasoning_chars += len(reasoning)
        if delta.content:
            content_chars += len(delta.content)
            yield delta.content
        if choice.finish_reason:
            finish_reason = choice.finish_reason

    logger.info(
        "LLM %s: %d karaktere përgjigje, %d karaktere arsyetim, finish_reason=%s",
        settings.llm_model, content_chars, reasoning_chars, finish_reason,
    )
    if content_chars == 0:
        raise EmptyAnswerError(
            f"Modeli {settings.llm_model} nuk ktheu tekst "
            f"(finish_reason={finish_reason}, arsyetim={reasoning_chars} karaktere). "
            "Nëse finish_reason është 'length', rrite LLM_MAX_TOKENS ose zgjidh një model pa arsyetim."
        )


def diagnose() -> dict:
    """Një kërkesë e vogël provë, pa streaming, për të parë çfarë kthen modeli."""
    response = _client().chat.completions.create(
        model=settings.llm_model,
        messages=[
            {"role": "system", "content": "Përgjigju shkurt në gjuhën shqipe."},
            {"role": "user", "content": "Sa është 2 + 2? Përgjigju me një fjali."},
        ],
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
    )
    choice = response.choices[0]
    message = choice.message
    reasoning = getattr(message, "reasoning_content", None) or getattr(message, "reasoning", None) or ""
    return {
        "base_url": settings.llm_base_url,
        "model_kerkuar": settings.llm_model,
        "model_pergjigjur": response.model,
        "max_tokens": settings.llm_max_tokens,
        "finish_reason": choice.finish_reason,
        "content": message.content,
        "reasoning_karaktere": len(reasoning),
        "usage": response.usage.model_dump() if response.usage else None,
    }
