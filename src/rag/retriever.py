"""Context retriever for the AI Mail Agent RAG pipeline.

:class:`ContextRetriever` bridges the vector store and the LangGraph agent
nodes.  It builds targeted queries from inbound mail, retrieves relevant
historical context, and stores new interactions so the knowledge base grows
over time.

Usage::

    from src.rag.retriever import ContextRetriever
    from src.rag.vectorstore import VectorStoreManager

    mgr = VectorStoreManager("./chroma_db")
    retriever = ContextRetriever(mgr)

    snippets = retriever.retrieve_context(mail_input, classification)
    # ... agent drafts a reply ...
    retriever.store_interaction(mail_input, classification, reply="...")
"""

from __future__ import annotations

import logging
from typing import Optional

from src.graph.state import ClassificationResult, MailInput
from src.rag.vectorstore import VectorStoreManager

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Categories for which a same-category filter meaningfully narrows results.
# "general" and "needs_human" are deliberately omitted — broad context is
# more useful for those cases.
_FILTERABLE_CATEGORIES: frozenset[str] = frozenset(
    {
        "tech_question",
        "code_review",
        "bug_report",
    }
)

_DEFAULT_TOP_K = 5

# Maximum characters to use from the email body when constructing the query.
# Keeps the embedded query concise while still capturing the core content.
_BODY_QUERY_CHARS = 500


class ContextRetriever:
    """Retrieves and stores email context using the underlying vector store.

    Each call to :meth:`retrieve_context` performs a similarity search tuned
    to the specific email and its classification.  Results are returned as
    plain strings ready to be injected into an LLM prompt.

    :meth:`store_interaction` indexes both the inbound email and the
    AI-generated reply, growing the knowledge base for future retrievals.

    Args:
        vectorstore_manager: An initialised :class:`VectorStoreManager`
            instance pointing at the desired ChromaDB persist directory.

    Example::

        mgr = VectorStoreManager("./chroma_db")
        retriever = ContextRetriever(mgr)

        snippets = retriever.retrieve_context(mail, classification)
        reply = draft_agent.run(mail, snippets)
        retriever.store_interaction(mail, classification, reply)
    """

    def __init__(self, vectorstore_manager: VectorStoreManager) -> None:
        self._vsm = vectorstore_manager

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def retrieve_context(
        self,
        mail_input: MailInput,
        classification: ClassificationResult,
        k: int = _DEFAULT_TOP_K,
    ) -> list[str]:
        """Retrieve the most relevant historical context for a given email.

        Builds a query by combining the email subject with the first
        :data:`_BODY_QUERY_CHARS` characters of the body.  If the email
        belongs to a filterable category, the search is scoped to documents
        with the same category label, which improves precision.

        Args:
            mail_input: The inbound email to retrieve context for.
            classification: The classifier's result, used to optionally scope
                the search to a matching category.
            k: Maximum number of context snippets to return.  Defaults to
                :data:`_DEFAULT_TOP_K`.

        Returns:
            list[str]: Up to *k* plain-text context strings, each
                corresponding to a stored document chunk.  Returns an empty
                list if the collection is empty or no relevant documents
                are found.
        """
        query = self._build_query(mail_input)
        filter_dict = self._build_filter(classification)

        logger.debug(
            "Retrieving context for email %s (category=%r, k=%d, filter=%s).",
            mail_input.message_id,
            classification.category,
            k,
            filter_dict,
        )

        docs = self._vsm.search(query=query, k=k, filter_dict=filter_dict)

        # If a category filter yielded no results, fall back to an unfiltered
        # search so the agent always has *something* to work with.
        if not docs and filter_dict is not None:
            logger.debug(
                "Filtered search returned 0 results for email %s; "
                "falling back to unfiltered search.",
                mail_input.message_id,
            )
            docs = self._vsm.search(query=query, k=k, filter_dict=None)

        snippets: list[str] = [doc.page_content for doc in docs]
        logger.info(
            "Retrieved %d context snippet(s) for email %s.",
            len(snippets),
            mail_input.message_id,
        )
        return snippets

    def store_interaction(
        self,
        mail_input: MailInput,
        classification: ClassificationResult,
        reply: str,
    ) -> None:
        """Persist an inbound email and its AI-generated reply in the vector store.

        Calling this method after each successful interaction ensures that
        future retrievals can benefit from the accumulated history of handled
        emails and their corresponding replies.

        Args:
            mail_input: The original inbound email.
            classification: Classification result for the email; the category
                label is stored as metadata on both email and reply documents.
            reply: The final, approved reply text to store.
        """
        date_str = self._format_date(mail_input)

        logger.info(
            "Storing interaction for email %s (category=%r).",
            mail_input.message_id,
            classification.category,
        )

        self._vsm.add_email(
            email_id=mail_input.message_id,
            subject=mail_input.subject,
            body=mail_input.body,
            sender=mail_input.sender,
            category=classification.category,
            date=date_str,
        )

        self._vsm.add_reply(
            email_id=mail_input.message_id,
            reply_body=reply,
            category=classification.category,
            date=date_str,
        )

        logger.info(
            "Interaction stored for email %s.", mail_input.message_id
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_query(self, mail_input: MailInput) -> str:
        """Construct the similarity-search query string from the email.

        The query is formed by prepending the subject line to a truncated
        slice of the body.  This ensures the semantic intent of the email is
        captured concisely without exceeding the embedding model's optimal
        input length.

        Args:
            mail_input: The inbound email.

        Returns:
            str: A combined query string.
        """
        body_excerpt = mail_input.body[:_BODY_QUERY_CHARS].strip()
        query = f"{mail_input.subject}\n\n{body_excerpt}"
        return query

    def _build_filter(
        self, classification: ClassificationResult
    ) -> Optional[dict[str, str]]:
        """Build a ChromaDB metadata filter dict for the given classification.

        Only categories listed in :data:`_FILTERABLE_CATEGORIES` trigger a
        filter; all others return ``None`` so the search remains unscoped.

        Args:
            classification: The classifier's result.

        Returns:
            dict[str, str] | None: A ``{"category": <value>}`` filter dict,
                or ``None`` if no scoping is appropriate.
        """
        if classification.category in _FILTERABLE_CATEGORIES:
            return {"category": classification.category}
        return None

    @staticmethod
    def _format_date(mail_input: MailInput) -> str:
        """Extract an ISO-8601 date string from the email's ``received_at`` field.

        Args:
            mail_input: The inbound email.

        Returns:
            str: Date in ``"YYYY-MM-DD"`` format.
        """
        return mail_input.received_at.strftime("%Y-%m-%d")
