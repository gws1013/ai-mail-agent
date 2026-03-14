"""Embedding function provider for vector store."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_embedding_fn = None


def get_embedding_function():
    """Return a cached HuggingFace embedding function.

    Uses sentence-transformers/all-MiniLM-L6-v2 for lightweight embeddings.
    """
    global _embedding_fn
    if _embedding_fn is None:
        try:
            from langchain_huggingface import HuggingFaceEmbeddings
        except ImportError:
            from langchain_community.embeddings import HuggingFaceEmbeddings

        _embedding_fn = HuggingFaceEmbeddings(
            model_name="sentence-transformers/all-MiniLM-L6-v2",
        )
        logger.info("Embedding model loaded: all-MiniLM-L6-v2")
    return _embedding_fn
