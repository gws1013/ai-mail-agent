"""
LangGraph state definitions for the AI Mail Agent pipeline.

Each Pydantic model represents the output of a single graph node.
``AgentState`` is the overall TypedDict that LangGraph passes between nodes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field
from typing_extensions import TypedDict


# --------------------------------------------------------------------------- #
# Node input / output models
# --------------------------------------------------------------------------- #


class MailInput(BaseModel):
    """Raw email data ingested at the start of the pipeline."""

    subject: str = Field(description="Email subject line.")
    sender: str = Field(description="RFC-5321 envelope sender address.")
    body: str = Field(description="Plain-text email body.")
    has_attachments: bool = Field(
        default=False,
        description="True when the message contains one or more attachments.",
    )
    message_id: str = Field(description="Gmail message ID (immutable).")
    thread_id: str = Field(description="Gmail thread ID the message belongs to.")
    received_at: datetime = Field(
        description="UTC timestamp at which the message was received.",
    )


class ClassificationResult(BaseModel):
    """Output of the classification node."""

    category: Literal[
        "tech_question",
        "code_review",
        "bug_report",
        "general",
        "spam",
        "needs_human",
    ] = Field(description="Primary category assigned to the email.")
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Model confidence in the assigned category (0 – 1).",
    )
    reasoning: str = Field(
        description="Free-text explanation of why this category was chosen.",
    )
    priority: Literal["high", "medium", "low"] = Field(
        description="Urgency level derived from email content and category.",
    )


class AnalysisResult(BaseModel):
    """Output of the deep-analysis node."""

    tech_stack: list[str] = Field(
        default_factory=list,
        description="Technologies, frameworks, or languages mentioned in the email.",
    )
    core_questions: list[str] = Field(
        default_factory=list,
        description="Discrete questions or asks extracted from the email body.",
    )
    related_context: list[str] = Field(
        default_factory=list,
        description="Relevant passages retrieved from the RAG knowledge base.",
    )
    code_snippets: list[str] = Field(
        default_factory=list,
        description="Code blocks extracted verbatim from the email.",
    )
    suggested_approach: str = Field(
        default="",
        description="High-level strategy the draft node should follow when replying.",
    )


class DraftResult(BaseModel):
    """Output of the draft-generation node."""

    subject: str = Field(description="Reply subject line (usually 'Re: …').")
    body: str = Field(description="Plain-text version of the reply body.")
    body_html: str = Field(description="HTML version of the reply body.")
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Model self-assessed confidence in the draft quality (0 – 1).",
    )
    tone_check: str = Field(
        description=(
            "Brief self-assessment of the reply tone "
            "(e.g. 'professional', 'too casual')."
        ),
    )


class ReviewResult(BaseModel):
    """Output of the review / quality-gate node."""

    approved: bool = Field(
        description="True when the draft passes all quality checks.",
    )
    issues: list[str] = Field(
        default_factory=list,
        description="List of problems found during review (empty when approved).",
    )
    technical_accuracy: float = Field(
        ge=0.0,
        le=1.0,
        description="Estimated correctness of technical claims in the draft (0 – 1).",
    )
    tone_appropriate: bool = Field(
        description="True when the reply tone is suitable for the recipient.",
    )
    contains_sensitive_info: bool = Field(
        description=(
            "True when the draft contains potentially sensitive or confidential "
            "information that should not be sent."
        ),
    )
    revised_body: Optional[str] = Field(
        default=None,
        description=(
            "Corrected plain-text body produced by the reviewer when "
            "``approved`` is False and an automatic fix is possible."
        ),
    )


# --------------------------------------------------------------------------- #
# LangGraph overall state
# --------------------------------------------------------------------------- #


class AgentState(TypedDict, total=False):
    """Mutable state dict threaded through every node of the LangGraph pipeline.

    All fields are optional (``total=False``) so that individual nodes only
    need to return the keys they modify; LangGraph merges partial updates.
    """

    raw_email: dict
    """Serialised :class:`MailInput` data (populated by the ingest node)."""

    classification: Optional[dict]
    """Serialised :class:`ClassificationResult` (populated by classify node)."""

    analysis: Optional[dict]
    """Serialised :class:`AnalysisResult` (populated by analysis node)."""

    draft: Optional[dict]
    """Serialised :class:`DraftResult` (populated by draft node)."""

    review: Optional[dict]
    """Serialised :class:`ReviewResult` (populated by review node)."""

    current_step: str
    """Name of the node that is currently executing or was last executed."""

    retry_count: int
    """Number of times the current step has been retried after a failure."""

    error: Optional[str]
    """Human-readable error message set when a node raises an exception."""

    final_action: str
    """
    Outcome decided at the end of the pipeline, e.g.:
    ``"sent"``, ``"queued_for_human"``, ``"discarded_spam"``, ``"failed"``.
    """
