"""ChromaDB vector store manager for the AI Mail Agent RAG pipeline.

Wraps LangChain's ``Chroma`` integration and provides high-level helpers for
indexing emails, storing AI-generated replies, and performing similarity search.

Usage::

    from src.rag.vectorstore import VectorStoreManager

    manager = VectorStoreManager(persist_directory="./chroma_db")
    collection = manager.get_or_create_collection("emails")

    manager.add_email(
        email_id="abc123",
        subject="How do I fix N+1 queries?",
        body="...",
        sender="user@example.com",
        category="technical_question",
        date="2026-03-13",
    )

    docs = manager.search("N+1 query optimisation", k=3)
"""

from __future__ import annotations

import logging
from typing import Optional

from langchain_core.documents import Document
from langchain_community.vectorstores import Chroma
from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.rag.embeddings import get_embedding_function

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CHUNK_SIZE = 500
_CHUNK_OVERLAP = 50


class VectorStoreManager:
    """Manages a ChromaDB-backed vector store for email indexing and retrieval.

    Each instance owns a single persist directory and exposes named
    collections inside it.  The most common collection is ``"emails"``,
    which stores both inbound email chunks and AI-generated replies.

    Args:
        persist_directory: Filesystem path where ChromaDB will persist its
            data.  The directory is created automatically if it does not exist.

    Attributes:
        persist_directory: The resolved persistence path.

    Example::

        mgr = VectorStoreManager("./chroma_db")
        mgr.add_email(email_id="1", subject="Hi", body="...",
                      sender="a@b.com", category="general", date="2026-01-01")
        results = mgr.search("deployment pipeline", k=5)
    """

    def __init__(self, persist_directory: str) -> None:
        self.persist_directory = persist_directory
        self._embedding_fn = get_embedding_function()
        self._collections: dict[str, Chroma] = {}
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=_CHUNK_SIZE,
            chunk_overlap=_CHUNK_OVERLAP,
            length_function=len,
        )
        logger.debug(
            "VectorStoreManager initialised (persist_dir=%s).", persist_directory
        )

    # ------------------------------------------------------------------
    # Collection management
    # ------------------------------------------------------------------

    def get_or_create_collection(self, name: str = "emails") -> Chroma:
        """Return an existing ChromaDB collection or create it on first access.

        Collections are cached in memory for the lifetime of this manager
        instance; repeated calls with the same *name* return the same object.

        Args:
            name: ChromaDB collection name.  Defaults to ``"emails"``.

        Returns:
            Chroma: A LangChain ``Chroma`` instance bound to the named
                collection inside :attr:`persist_directory`.
        """
        if name not in self._collections:
            logger.info("Opening/creating ChromaDB collection: %r", name)
            self._collections[name] = Chroma(
                collection_name=name,
                embedding_function=self._embedding_fn,
                persist_directory=self.persist_directory,
            )
        return self._collections[name]

    # ------------------------------------------------------------------
    # Indexing helpers
    # ------------------------------------------------------------------

    def add_email(
        self,
        email_id: str,
        subject: str,
        body: str,
        sender: str,
        category: str,
        date: str,
    ) -> None:
        """Chunk and index an inbound email into the ``"emails"`` collection.

        The email body is split into overlapping chunks using
        :class:`RecursiveCharacterTextSplitter`.  Each chunk is stored with a
        rich metadata payload so that downstream filters can narrow searches by
        sender, category, or date.

        Args:
            email_id: Unique Gmail message ID (used as part of the document ID
                to allow idempotent re-indexing).
            subject: Email subject line.  Prepended to the first chunk so that
                the subject context is always retrievable.
            body: Full email body text.
            sender: Sender email address.
            category: Classification label assigned by the Classifier agent
                (e.g. ``"technical_question"``, ``"code_review"``).
            date: ISO-8601 date string of the email (``"YYYY-MM-DD"``).
        """
        collection = self.get_or_create_collection("emails")

        # Prepend subject so it appears in context for every search
        full_text = f"Subject: {subject}\n\n{body}"
        chunks: list[str] = self._splitter.split_text(full_text)

        if not chunks:
            logger.warning("Email %s produced no text chunks; skipping.", email_id)
            return

        base_metadata: dict[str, str] = {
            "email_id": email_id,
            "subject": subject,
            "sender": sender,
            "category": category,
            "date": date,
            "doc_type": "email",
        }

        documents = [
            Document(page_content=chunk, metadata={**base_metadata, "chunk_index": str(i)})
            for i, chunk in enumerate(chunks)
        ]
        ids = [f"{email_id}_chunk_{i}" for i in range(len(chunks))]

        collection.add_documents(documents=documents, ids=ids)
        logger.info(
            "Indexed email %s (%d chunk(s), category=%r).",
            email_id,
            len(chunks),
            category,
        )

    def add_reply(
        self,
        email_id: str,
        reply_body: str,
        category: str,
        date: str,
    ) -> None:
        """Store an AI-generated reply for future RAG retrieval.

        Replies are indexed in the same ``"emails"`` collection under the
        ``doc_type="reply"`` tag so they can be retrieved as positive examples
        of well-formed responses for similar future emails.

        Args:
            email_id: Gmail message ID of the original email that was replied
                to.  Used to construct a deterministic document ID.
            reply_body: Full text of the AI-generated reply.
            category: Classification category of the original email.
            date: ISO-8601 date string when the reply was sent.
        """
        collection = self.get_or_create_collection("emails")

        chunks: list[str] = self._splitter.split_text(reply_body)
        if not chunks:
            logger.warning(
                "Reply for email %s produced no text chunks; skipping.", email_id
            )
            return

        base_metadata: dict[str, str] = {
            "email_id": email_id,
            "category": category,
            "date": date,
            "doc_type": "reply",
        }

        documents = [
            Document(
                page_content=chunk,
                metadata={**base_metadata, "chunk_index": str(i)},
            )
            for i, chunk in enumerate(chunks)
        ]
        ids = [f"{email_id}_reply_chunk_{i}" for i in range(len(chunks))]

        collection.add_documents(documents=documents, ids=ids)
        logger.info(
            "Indexed reply for email %s (%d chunk(s)).", email_id, len(chunks)
        )

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        k: int = 5,
        filter_dict: Optional[dict[str, str]] = None,
    ) -> list[Document]:
        """Perform similarity search against the ``"emails"`` collection.

        Args:
            query: Natural-language query string to embed and search with.
            k: Maximum number of documents to return.  Defaults to ``5``.
            filter_dict: Optional ChromaDB ``where`` filter expressed as a
                plain ``{field: value}`` mapping.  When provided, only
                documents whose metadata satisfies the filter are considered.
                Example: ``{"category": "technical_question"}``.

        Returns:
            list[Document]: Up to *k* :class:`~langchain.schema.Document`
                objects ordered by descending similarity.  Returns an empty
                list if the collection is empty.
        """
        collection = self.get_or_create_collection("emails")

        try:
            results: list[Document] = collection.similarity_search(
                query=query,
                k=k,
                filter=filter_dict,
            )
        except Exception:
            # ChromaDB raises if the collection is empty; degrade gracefully.
            logger.debug(
                "Similarity search returned no results (collection may be empty).",
                exc_info=True,
            )
            results = []

        logger.debug("Search for %r returned %d document(s).", query, len(results))
        return results

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def get_stats(self) -> dict[str, object]:
        """Return runtime statistics for the ``"emails"`` collection.

        Queries ChromaDB for the total document count and computes a
        per-category breakdown using metadata filtering.

        Returns:
            dict: A dictionary with the following keys:

            - ``"total_documents"`` (int): Total number of chunks stored.
            - ``"categories"`` (dict[str, int]): Mapping of category label to
              chunk count.

        Example::

            stats = manager.get_stats()
            # {"total_documents": 42, "categories": {"technical_question": 30, ...}}
        """
        collection = self.get_or_create_collection("emails")
        chroma_collection = collection._collection  # type: ignore[attr-defined]

        total: int = chroma_collection.count()

        # Fetch all metadata to compute per-category counts without loading
        # the actual embedding vectors.
        all_metadata = chroma_collection.get(include=["metadatas"])
        metadatas: list[dict[str, str]] = all_metadata.get("metadatas") or []

        categories: dict[str, int] = {}
        for meta in metadatas:
            cat = meta.get("category", "unknown")
            categories[cat] = categories.get(cat, 0) + 1

        stats: dict[str, object] = {
            "total_documents": total,
            "categories": categories,
        }
        logger.debug("Collection stats: %s", stats)
        return stats
