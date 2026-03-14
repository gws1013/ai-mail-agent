"""RAG retriever for contract and care record search."""

from __future__ import annotations

import logging
from typing import Any

from src.graph.state import ClassificationResult, MailInput
from src.rag.vectorstore import VectorStoreManager

logger = logging.getLogger(__name__)


class ContextRetriever:
    """Retrieve relevant context from vector store collections.

    Args:
        store_manager: VectorStoreManager instance.
    """

    def __init__(self, store_manager: VectorStoreManager) -> None:
        self._store = store_manager

    def retrieve_contracts(self, query: str, k: int = 5) -> list[str]:
        """Search contracts collection for relevant passages.

        Args:
            query: Search query text.
            k: Number of results to return.

        Returns:
            List of relevant text passages.
        """
        return self._search("contracts", query, k)

    def retrieve_care_records(self, query: str, k: int = 5) -> list[str]:
        """Search care_records collection for relevant passages.

        Uses name-based metadata filtering when a person name is found
        in the query, falling back to similarity search.

        Args:
            query: Search query text.
            k: Number of results to return.

        Returns:
            List of relevant text passages.
        """
        # Try to find a matching person by scanning source_file metadata
        try:
            collection = self._store.get_or_create_collection("care_records")
            all_data = collection.get()
            matched_source = None

            for meta in all_data["metadatas"]:
                source = meta.get("source_file", "")
                # Extract name from filename like "care_record_01_박순자.pdf"
                parts = source.replace(".pdf", "").split("_")
                if len(parts) >= 3:
                    name = parts[-1]
                    if name and name in query:
                        matched_source = source
                        break

            if matched_source:
                logger.info("Care records: filtering by source_file=%s", matched_source)
                docs = collection.similarity_search(
                    query, k=k,
                    filter={"source_file": matched_source},
                )
                return [doc.page_content for doc in docs]
        except Exception:
            logger.exception("Care record name filter failed, falling back.")

        return self._search("care_records", query, k)

    def retrieve_context(
        self,
        mail_input: MailInput,
        classification: ClassificationResult,
        k: int = 5,
    ) -> list[str]:
        """Auto-select collection based on classification and retrieve context.

        Args:
            mail_input: Parsed email input.
            classification: Classification result.
            k: Number of results.

        Returns:
            List of relevant text passages.
        """
        query = f"{mail_input.subject} {mail_input.body[:500]}"
        category = classification.category

        if category == "contract_inquiry":
            return self.retrieve_contracts(query, k)
        elif category == "care_record":
            return self.retrieve_care_records(query, k)
        else:
            # Try contracts as fallback
            return self.retrieve_contracts(query, k)

    def _search(self, collection_name: str, query: str, k: int) -> list[str]:
        """Perform similarity search on a collection.

        Args:
            collection_name: Name of the Chroma collection.
            query: Search query.
            k: Number of results.

        Returns:
            List of document text strings.
        """
        try:
            collection = self._store.get_or_create_collection(collection_name)
            docs = collection.similarity_search(query, k=k)
            results = [doc.page_content for doc in docs]
            logger.debug(
                "Retrieved %d results from '%s' for query: %s...",
                len(results), collection_name, query[:80],
            )
            return results
        except Exception:
            logger.exception("RAG search failed on collection '%s'.", collection_name)
            return []
