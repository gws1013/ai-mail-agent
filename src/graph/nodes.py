"""LangGraph node functions for the mail agent workflow."""

from __future__ import annotations

import logging
from typing import Any

from src.graph.state import (
    AgentState, MailInput, ClassificationResult,
    DraftResult, CareReportResult, SchedulerResult,
)
from src.agents.classifier import ClassifierAgent
from src.agents.signer import SignerAgent
from src.agents.contract_replier import ContractReplierAgent
from src.agents.care_reporter import CareReporterAgent
from src.agents.scheduler import SchedulerAgent
from src.agents.reviewer import ReviewerAgent
from src.mail.sender import EmailSender
from src.mail.attachment import download_attachments
from src.rag.retriever import ContextRetriever
from src.utils.notifier import notify

logger = logging.getLogger(__name__)

# Injected by orchestrator.init_agents()
_classifier: ClassifierAgent | None = None
_signer: SignerAgent | None = None
_contract_replier: ContractReplierAgent | None = None
_care_reporter: CareReporterAgent | None = None
_scheduler: SchedulerAgent | None = None
_reviewer: ReviewerAgent | None = None
_sender: EmailSender | None = None
_retriever: ContextRetriever | None = None
_gmail_client: Any = None


def init_agents(
    classifier: ClassifierAgent,
    signer: SignerAgent,
    contract_replier: ContractReplierAgent,
    care_reporter: CareReporterAgent,
    scheduler: SchedulerAgent,
    reviewer: ReviewerAgent,
    sender: EmailSender,
    retriever: ContextRetriever,
    gmail_client: Any,
) -> None:
    """Inject agent references for node functions."""
    global _classifier, _signer, _contract_replier, _care_reporter
    global _scheduler, _reviewer, _sender, _retriever, _gmail_client
    _classifier = classifier
    _signer = signer
    _contract_replier = contract_replier
    _care_reporter = care_reporter
    _scheduler = scheduler
    _reviewer = reviewer
    _sender = sender
    _retriever = retriever
    _gmail_client = gmail_client


# ── Classify ─────────────────────────────────────────────────────

def classify_node(state: AgentState) -> dict:
    """Classify the incoming email."""
    logger.info("Classifying email...")
    raw = state["raw_email"]

    try:
        mail_input = MailInput(**raw)
        result = _classifier.classify(mail_input)
        logger.info(
            "Classification: %s (probs: %s)",
            result.category, result.probabilities,
        )
        return {
            "classification": result.model_dump(),
            "current_step": "classified",
        }
    except Exception as e:
        logger.error("Classification failed: %s", e)
        return {
            "classification": {
                "category": "spam_or_other",
                "probabilities": {},
                "reasoning": f"분류 오류: {e}",
            },
            "current_step": "classified",
            "error": str(e),
        }


# ── Signature processing ────────────────────────────────────────

def signer_node(state: AgentState) -> dict:
    """Download attachments and process signature request."""
    logger.info("Processing signature request...")
    raw = state["raw_email"]
    mail_input = MailInput(**raw)

    # Download attachments
    att_metadata = raw.get("attachments", [])
    if not att_metadata and mail_input.has_attachments:
        detail = _gmail_client.get_email_detail(mail_input.message_id)
        att_metadata = detail.get("attachments", [])

    paths = []
    if att_metadata:
        paths = download_attachments(
            _gmail_client, mail_input.message_id, att_metadata
        )

    result = _signer.process(mail_input, paths)

    # Save to drafts
    try:
        _sender.save_draft(
            raw, result.reply_body,
            attachment_path=result.signed_file_path or None,
        )
        logger.info("Signature draft saved to Gmail drafts.")
    except Exception:
        logger.exception("Failed to save signature draft.")

    notify(
        title="서명 요청 처리 — 임시보관함 확인",
        message=f"보낸이: {mail_input.sender}\n제목: {mail_input.subject}",
    )

    return {
        "signer_result": result.model_dump(),
        "attachments": paths,
        "current_step": "signed",
        "final_action": "drafted",
    }


# ── Contract reply ───────────────────────────────────────────────

def contract_reply_node(state: AgentState) -> dict:
    """Draft a reply based on contract context."""
    logger.info("Drafting contract reply...")
    raw = state["raw_email"]
    mail_input = MailInput(**raw)
    classification = ClassificationResult(**state["classification"])

    context = _retriever.retrieve_context(mail_input, classification)
    result = _contract_replier.draft(mail_input, context)

    return {
        "draft": result.model_dump(),
        "current_step": "drafted",
    }


# ── Care record report ──────────────────────────────────────────

def care_report_node(state: AgentState) -> dict:
    """Draft a care record report for review and auto-send."""
    logger.info("Drafting care record report...")
    raw = state["raw_email"]
    mail_input = MailInput(**raw)

    care_data = _retriever.retrieve_care_records(
        f"{mail_input.subject} {mail_input.body[:500]}"
    )
    result = _care_reporter.draft_report(mail_input, care_data)

    # Find matching PDF to attach
    from pathlib import Path
    pdf_paths = []
    if result.patient_name:
        care_dir = Path("data/care_records")
        if care_dir.exists():
            for pdf in care_dir.glob("*.pdf"):
                if result.patient_name in pdf.name:
                    pdf_paths.append(str(pdf))
                    logger.info("Attaching care record PDF: %s", pdf.name)

    return {
        "care_report": result.model_dump(),
        "draft": DraftResult(
            body=result.body,
            confidence=0.8,
        ).model_dump(),
        "attachments": pdf_paths,
        "current_step": "care_reported",
    }


# ── Reservation reply ───────────────────────────────────────────

def scheduler_node(state: AgentState) -> dict:
    """Draft a reservation/visit reply."""
    logger.info("Drafting reservation reply...")
    raw = state["raw_email"]
    mail_input = MailInput(**raw)

    result = _scheduler.draft_reply(mail_input)

    return {
        "scheduler_result": result.model_dump(),
        "draft": DraftResult(
            body=result.body,
            confidence=0.8,
        ).model_dump(),
        "current_step": "scheduled",
    }


# ── Review ───────────────────────────────────────────────────────

def review_node(state: AgentState) -> dict:
    """Review the draft reply."""
    logger.info("Reviewing draft...")
    raw = state["raw_email"]
    mail_input = MailInput(**raw)
    draft = state.get("draft", {})
    draft_body = draft.get("body", "")

    try:
        result = _reviewer.review(mail_input, draft_body)
        logger.info("Review: %s", "APPROVED" if result.approved else "REJECTED")
        return {
            "review": result.model_dump(),
            "current_step": "reviewed",
        }
    except Exception as e:
        logger.error("Review failed: %s", e)
        return {
            "review": {
                "approved": False,
                "issues": [f"리뷰 오류: {e}"],
                "tone_appropriate": False,
                "contains_sensitive_info": False,
                "revised_body": None,
            },
            "current_step": "reviewed",
            "error": str(e),
        }


# ── Send ─────────────────────────────────────────────────────────

def send_node(state: AgentState) -> dict:
    """Send the approved reply."""
    logger.info("Sending reply...")
    raw = state["raw_email"]
    draft = state.get("draft", {})
    review = state.get("review", {})

    body = review.get("revised_body") or draft.get("body", "")
    attachments = state.get("attachments", [])
    attachment = attachments[0] if attachments else None

    try:
        _sender.send_reply(raw, body, attachment_path=attachment)
        logger.info("Reply sent to %s", raw.get("sender", "unknown"))

        notify(
            title="메일 자동 답장 완료",
            message=f"받는이: {raw.get('sender', '')}\n제목: Re: {raw.get('subject', '')}",
        )

        return {"current_step": "sent", "final_action": "sent"}
    except Exception as e:
        logger.error("Send failed: %s", e)
        return {"error": str(e), "current_step": "send_failed", "final_action": "error"}


# ── Skip ─────────────────────────────────────────────────────────

def skip_node(state: AgentState) -> dict:
    """Skip spam/irrelevant emails."""
    logger.info("Skipping email (spam/other)")
    return {"current_step": "skipped", "final_action": "skipped"}
