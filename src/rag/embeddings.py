"""Embedding function provider for RAG pipeline.

Provides a module-level singleton HuggingFace embedding function backed by
the ``all-MiniLM-L6-v2`` sentence-transformer model (small, fast, CPU-friendly,
no API key required).

Usage::

    from src.rag.embeddings import get_embedding_function

    embed_fn = get_embedding_function()  # cached — safe to call repeatedly
"""

from __future__ import annotations

import logging
from typing import Optional

from langchain_community.embeddings import HuggingFaceEmbeddings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_embedding_function: Optional[HuggingFaceEmbeddings] = None

_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


def get_embedding_function() -> HuggingFaceEmbeddings:
    """Return the shared :class:`HuggingFaceEmbeddings` singleton.

    The embedding model is loaded once on first call and reused on all
    subsequent calls, avoiding repeated disk I/O and model initialisation
    overhead.

    The ``all-MiniLM-L6-v2`` model produces 384-dimensional dense vectors and
    runs efficiently on CPU, making it well-suited for local deployments without
    GPU resources or external API costs.

    Returns:
        HuggingFaceEmbeddings: A LangChain-compatible embedding function that
            can be passed directly to ``Chroma`` or any other LangChain
            vector store.

    Example::

        embed_fn = get_embedding_function()
        vectors = embed_fn.embed_documents(["hello world"])
    """
    global _embedding_function

    if _embedding_function is None:
        logger.info("Initialising HuggingFace embedding model: %s", _MODEL_NAME)
        _embedding_function = HuggingFaceEmbeddings(
            model_name=_MODEL_NAME,
            model_kwargs={"device": "cpu"},
            encode_kwargs={"normalize_embeddings": True},
        )
        logger.info("Embedding model loaded successfully.")

    return _embedding_function
