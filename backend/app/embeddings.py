"""Embeddings lokale me fastembed (ONNX, pa GPU, pa API të jashtme)."""

from functools import lru_cache

from fastembed import TextEmbedding

from .config import settings


@lru_cache(maxsize=1)
def _model() -> TextEmbedding:
    return TextEmbedding(model_name=settings.embedding_model, cache_dir=settings.embedding_cache_dir)


def embed(texts: list[str]) -> list[list[float]]:
    return [vector.tolist() for vector in _model().embed(texts)]


def embed_one(text: str) -> list[float]:
    return embed([text])[0]
