"""Semantic similarity helpers for EvaliSense answer evaluation.

Uses ``sentence-transformers`` to encode text and compute cosine
similarity.  The model is loaded lazily and cached so that repeated
calls do not re-download or re-initialise the model.

The default model (``all-MiniLM-L6-v2``) is small enough (~80 MB) to
run on CPU with acceptable latency.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from utils.logging import get_logger

logger = get_logger(__name__)

# Module-level cache for the embedding model.
_model: Any = None
_model_name: str | None = None


def _load_model(model_name: str = "all-MiniLM-L6-v2") -> Any:
    """Load the sentence-transformer model (cached)."""
    global _model, _model_name
    if _model is not None and _model_name == model_name:
        return _model
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError(
            "Semantic evaluation requires sentence-transformers. "
            "Install it with: pip install sentence-transformers"
        ) from exc
    logger.info("Loading embedding model: %s", model_name)
    _model = SentenceTransformer(model_name)
    _model_name = model_name
    logger.info("Embedding model loaded successfully")
    return _model


def encode(texts: list[str], model_name: str = "all-MiniLM-L6-v2") -> np.ndarray:
    """Encode a list of texts into dense vectors."""
    model = _load_model(model_name)
    return model.encode(texts, convert_to_numpy=True, show_progress_bar=False)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity between two vectors."""
    a_flat = a.flatten().astype(np.float64)
    b_flat = b.flatten().astype(np.float64)
    norm_a = np.linalg.norm(a_flat)
    norm_b = np.linalg.norm(b_flat)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a_flat, b_flat) / (norm_a * norm_b))


def semantic_similarity(
    text_a: str,
    text_b: str,
    model_name: str = "all-MiniLM-L6-v2",
) -> float:
    """Return the cosine similarity between two text passages."""
    if not text_a.strip() or not text_b.strip():
        return 0.0
    embeddings = encode([text_a, text_b], model_name)
    return cosine_similarity(embeddings[0], embeddings[1])


def batch_similarity(
    query: str,
    candidates: list[str],
    model_name: str = "all-MiniLM-L6-v2",
) -> list[float]:
    """Return cosine similarities between *query* and each candidate."""
    if not query.strip() or not candidates:
        return [0.0] * len(candidates)
    all_texts = [query] + candidates
    embeddings = encode(all_texts, model_name)
    query_emb = embeddings[0]
    return [
        cosine_similarity(query_emb, embeddings[i + 1])
        for i in range(len(candidates))
    ]
