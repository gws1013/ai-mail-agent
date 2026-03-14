"""LangGraph node functions for the mail agent workflow."""

import logging
from src.graph.state import AgentState, MailInput, ClassificationResult, AnalysisResult, DraftResult, ReviewResult
from src.agents.classifier import ClassifierAgent
from src.agents.analyzer import AnalyzerAgent
from src.agents.drafter import DrafterAgent
from src.agents.reviewer import ReviewerAgent
from src.mail.gmail_client import GmailClient
from src.mail.sender import EmailSender
from src.rag.retriever import ContextRetriever
from src.config import get_settings
from src.utils.notifier import notify

logger = logging.getLogger(__name__)

# These will be initialized in workflow.py and injected
_classifier: ClassifierAgent | None = None
_analyzer: AnalyzerAgent | None = None
_drafter: DrafterAgent | None = None
_reviewer: ReviewerAgent | None = None
_sender: EmailSender | None = None
_retriever: ContextRetriever | None = None


def init_agents(
    classifier: ClassifierAgent,
    analyzer: AnalyzerAgent,
    drafter: DrafterAgent,
    reviewer: ReviewerAgent,
    sender: EmailSender,
    retriever: ContextRetriever,
) -> None:
    """Initialize agent references for node functions."""
    global _classifier, _analyzer, _drafter, _reviewer, _sender, _retriever
    _classifier = classifier
    _analyzer = analyzer
    _drafter = drafter
    _reviewer = reviewer
    _sender = sender
    _retriever = retriever


_NOREPLY_PATTERNS = [
    "noreply", "no-reply", "no_reply", "donotreply", "do-not-reply",
    "mailer-daemon", "postmaster",
]

_AD_SENDER_PATTERNS = [
    "newsletter", "promo", "marketing", "notification", "alert",
    "deals", "offer", "coupon", "digest",
]


def _is_auto_skip(sender: str) -> str | None:
    """Return a skip reason if the sender looks like noreply/ad, else None."""
    sender_lower = sender.lower()
    for pat in _NOREPLY_PATTERNS:
        if pat in sender_lower:
            return f"noreply 발신자 ({sender})"
    for pat in _AD_SENDER_PATTERNS:
        if pat in sender_lower:
            return f"광고성 발신자 ({sender})"
    return None


def classify_node(state: AgentState) -> dict:
    """Classify the incoming email."""
    logger.info("Classifying email...")

    raw_email = state["raw_email"]
    sender = raw_email.get("sender", "")

    # Fast pre-filter: skip noreply/ad senders without calling LLM
    skip_reason = _is_auto_skip(sender)
    if skip_reason:
        logger.info(f"Auto-skip: {skip_reason}")
        return {
            "classification": {
                "category": "spam",
                "confidence": 1.0,
                "reasoning": skip_reason,
                "priority": "low",
            },
            "current_step": "classified",
        }

    try:
        mail_input = MailInput(**raw_email)
        result = _classifier.classify(mail_input)
        logger.info(f"Classification: {result.category} (confidence: {result.confidence})")
        return {
            "classification": result.model_dump(),
            "current_step": "classified",
        }
    except Exception as e:
        logger.error(f"Classification failed: {e}")
        return {
            "classification": {
                "category": "needs_human",
                "confidence": 0.0,
                "reasoning": f"Classification error: {str(e)}",
                "priority": "high",
            },
            "current_step": "classified",
            "error": str(e),
        }


def analyze_node(state: AgentState) -> dict:
    """Analyze the email context."""
    logger.info("Analyzing email context...")
    try:
        mail_input = MailInput(**state["raw_email"])
        classification = ClassificationResult(**state["classification"])
        result = _analyzer.analyze(mail_input, classification)
        logger.info(f"Analysis complete. Tech stack: {result.tech_stack}")
        return {
            "analysis": result.model_dump(),
            "current_step": "analyzed",
        }
    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        return {
            "analysis": {
                "tech_stack": [],
                "core_questions": [],
                "related_context": [],
                "code_snippets": [],
                "suggested_approach": "Analysis failed, proceed with basic reply.",
            },
            "current_step": "analyzed",
            "error": str(e),
        }


def draft_node(state: AgentState) -> dict:
    """Draft a reply email."""
    logger.info("Drafting reply...")
    try:
        mail_input = MailInput(**state["raw_email"])
        analysis = AnalysisResult(**state["analysis"])

        # Check if this is a redraft (reviewer feedback)
        feedback = None
        if state.get("review") and not state["review"].get("approved"):
            feedback = "; ".join(state["review"].get("issues", []))

        result = _drafter.draft(mail_input, analysis, feedback=feedback)
        logger.info(f"Draft complete. Confidence: {result.confidence}")
        return {
            "draft": result.model_dump(),
            "current_step": "drafted",
        }
    except Exception as e:
        logger.error(f"Drafting failed: {e}")
        return {
            "error": str(e),
            "current_step": "draft_failed",
        }


def review_node(state: AgentState) -> dict:
    """Review the draft reply."""
    logger.info("Reviewing draft...")
    try:
        mail_input = MailInput(**state["raw_email"])
        draft = DraftResult(**state["draft"])
        result = _reviewer.review(mail_input, draft)
        logger.info(f"Review: {'APPROVED' if result.approved else 'REJECTED'}")
        return {
            "review": result.model_dump(),
            "current_step": "reviewed",
        }
    except Exception as e:
        logger.error(f"Review failed: {e}")
        return {
            "review": {
                "approved": False,
                "issues": [f"Review error: {str(e)}"],
                "technical_accuracy": 0.0,
                "tone_appropriate": False,
                "contains_sensitive_info": False,
                "revised_body": None,
            },
            "current_step": "reviewed",
            "error": str(e),
        }


def send_node(state: AgentState) -> dict:
    """Send the approved reply."""
    logger.info("Sending reply...")
    try:
        draft = DraftResult(**state["draft"])
        review = ReviewResult(**state["review"])
        raw_email = state["raw_email"]

        # Map parsed MailInput keys back to Gmail API keys for sender
        sender_email = {
            "id": raw_email.get("message_id", ""),
            "threadId": raw_email.get("thread_id", ""),
            "sender": raw_email.get("sender", ""),
            "subject": raw_email.get("subject", ""),
            "body": raw_email.get("body", ""),
            "date": raw_email.get("received_at", "").strftime("%Y년 %m월 %d일 %H:%M")
            if hasattr(raw_email.get("received_at", ""), "strftime")
            else str(raw_email.get("received_at", "")),
        }
        result = _sender.send_reply(sender_email, draft, review)

        # Store interaction for RAG
        mail_input = MailInput(**raw_email)
        classification = ClassificationResult(**state["classification"])
        final_body = review.revised_body if review.revised_body else draft.body
        _retriever.store_interaction(mail_input, classification, final_body)

        logger.info(f"Reply sent successfully to {raw_email.get('sender', 'unknown')}")
        notify(
            title="메일 자동 답장 완료",
            message=f"받는이: {raw_email.get('sender', '알 수 없음')}\n제목: Re: {raw_email.get('subject', '')}",
        )
        return {
            "current_step": "sent",
            "final_action": "sent",
        }
    except Exception as e:
        logger.error(f"Send failed: {e}")
        return {
            "error": str(e),
            "current_step": "send_failed",
            "final_action": "error",
        }


def escalate_node(state: AgentState) -> dict:
    """Escalate to human review."""
    import re as _re

    logger.info("Escalating to human review...")
    reason = state.get("error") or "Low confidence or sensitive content"
    if state.get("classification"):
        reason = state["classification"].get("reasoning", reason)
    logger.warning(f"Escalation reason: {reason}")

    raw = state.get("raw_email", {})
    sender = raw.get("sender", "알 수 없음")
    subject = raw.get("subject", "(제목 없음)")

    # Save draft reply to Gmail Drafts if a draft body exists
    draft_data = state.get("draft")
    if draft_data and draft_data.get("body") and _sender:
        try:
            match = _re.search(r"<([^>]+)>", sender)
            to_addr = match.group(1) if match else sender
            draft_obj = DraftResult(**draft_data)
            reply_html = _sender._to_html(draft_obj.body)
            original_body = raw.get("body", "")
            original_date = (
                raw.get("received_at", "").strftime("%Y년 %m월 %d일 %H:%M")
                if hasattr(raw.get("received_at", ""), "strftime")
                else str(raw.get("received_at", ""))
            )
            quoted_html = _sender._build_quoted_reply(
                reply_html, original_body, sender, original_date,
            )
            _sender._client.create_draft(
                to=to_addr,
                subject=f"Re: {subject}" if not subject.lower().startswith("re:") else subject,
                body_html=quoted_html,
                thread_id=raw.get("thread_id", ""),
                in_reply_to=raw.get("message_id", ""),
            )
            logger.info("Draft saved for escalated email: %s", subject)
        except Exception:
            logger.exception("Failed to save draft for escalated email")

    # Desktop notification
    notify(
        title="메일 에스컬레이션 — 임시보관함 확인",
        message=f"보낸이: {sender}\n제목: {subject}\n사유: {reason[:80]}",
    )

    return {
        "current_step": "escalated",
        "final_action": "escalated",
    }


def skip_node(state: AgentState) -> dict:
    """Skip spam/irrelevant emails."""
    logger.info("Skipping email (spam/irrelevant)")
    return {
        "current_step": "skipped",
        "final_action": "skipped",
    }
