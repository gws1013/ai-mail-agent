"""Graph state definitions and Pydantic models for inter-agent communication."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field
from typing_extensions import TypedDict


# ── 입력 모델 ────────────────────────────────────────────────────

class MailInput(BaseModel):
    """Parsed email input shared across all agents."""

    message_id: str = ""
    thread_id: str = ""
    subject: str = ""
    sender: str = ""
    body: str = ""
    received_at: str = ""
    has_attachments: bool = False
    attachment_ids: list[str] = Field(default_factory=list)


# ── 분류 결과 ────────────────────────────────────────────────────

class ClassificationResult(BaseModel):
    """Classifier output with softmax probabilities."""

    category: str = "spam_or_other"
    probabilities: dict[str, float] = Field(default_factory=dict)
    reasoning: str = ""


# ── 분석 결과 ────────────────────────────────────────────────────

class AnalysisResult(BaseModel):
    """Context analysis output."""

    related_context: list[str] = Field(default_factory=list)
    patient_name: str = ""
    guardian_name: str = ""
    key_questions: list[str] = Field(default_factory=list)
    suggested_approach: str = ""


# ── 서명 처리 결과 ───────────────────────────────────────────────

class SignerResult(BaseModel):
    """Signer agent output."""

    signed_file_path: str = ""
    reply_body: str = ""
    confidence: float = 0.0


# ── 답변 초안 결과 ───────────────────────────────────────────────

class DraftResult(BaseModel):
    """Draft reply output."""

    body: str = ""
    sources: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    needs_escalation: bool = False


# ── 생활기록 보고서 결과 ─────────────────────────────────────────

class CareReportResult(BaseModel):
    """Care reporter agent output."""

    body: str = ""
    patient_name: str = ""
    guardian_name: str = ""
    period: str = ""


# ── 예약 확인 결과 ───────────────────────────────────────────────

class SchedulerResult(BaseModel):
    """Scheduler agent output."""

    body: str = ""
    available_dates: list[str] = Field(default_factory=list)
    has_vacancy: bool = False


# ── 리뷰 결과 ────────────────────────────────────────────────────

class ReviewResult(BaseModel):
    """Reviewer agent output."""

    approved: bool = False
    issues: list[str] = Field(default_factory=list)
    tone_appropriate: bool = True
    contains_sensitive_info: bool = False
    revised_body: Optional[str] = None


# ── LangGraph 상태 ───────────────────────────────────────────────

class AgentState(TypedDict, total=False):
    """LangGraph shared state across all nodes."""

    raw_email: dict[str, Any]
    classification: Optional[dict[str, Any]]
    analysis: Optional[dict[str, Any]]
    attachments: list[str]
    signer_result: Optional[dict[str, Any]]
    draft: Optional[dict[str, Any]]
    care_report: Optional[dict[str, Any]]
    scheduler_result: Optional[dict[str, Any]]
    review: Optional[dict[str, Any]]
    current_step: str
    final_action: str
    error: Optional[str]
    retry_count: int
