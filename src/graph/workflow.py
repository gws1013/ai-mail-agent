"""LangGraph workflow definition for the mail agent."""

from __future__ import annotations

import logging

from langgraph.graph import StateGraph, END

from src.graph.state import AgentState
from src.graph import nodes

logger = logging.getLogger(__name__)


def route_after_classify(state: AgentState) -> str:
    """Route to the appropriate handler based on classification category.

    Returns:
        Next node name string.
    """
    classification = state.get("classification", {})
    category = classification.get("category", "spam_or_other")

    route_map = {
        "signature_request": "signer",
        "contract_inquiry": "contract_reply",
        "care_record": "care_report",
        "reservation": "scheduler",
        "spam_or_other": "skip",
    }

    destination = route_map.get(category, "skip")
    logger.info("Routing '%s' → %s", category, destination)
    return destination


def route_after_review(state: AgentState) -> str:
    """Route after review: send if approved, redraft if rejected.

    Returns:
        Next node name string.
    """
    review = state.get("review", {})
    retry_count = state.get("retry_count", 0)

    if review.get("approved"):
        return "send"

    # Max 2 redraft attempts
    if retry_count >= 2:
        logger.warning("Max retries reached — sending to drafts instead.")
        return "escalate_draft"

    return "redraft"


def build_workflow() -> StateGraph:
    """Construct and compile the LangGraph workflow.

    Returns:
        Compiled StateGraph ready for invocation.
    """
    workflow = StateGraph(AgentState)

    # Add nodes
    workflow.add_node("classify", nodes.classify_node)
    workflow.add_node("signer", nodes.signer_node)
    workflow.add_node("contract_reply", nodes.contract_reply_node)
    workflow.add_node("care_report", nodes.care_report_node)
    workflow.add_node("scheduler", nodes.scheduler_node)
    workflow.add_node("review", nodes.review_node)
    workflow.add_node("send", nodes.send_node)
    workflow.add_node("skip", nodes.skip_node)
    workflow.add_node("redraft", _redraft_node)
    workflow.add_node("escalate_draft", _escalate_draft_node)

    # Entry point
    workflow.set_entry_point("classify")

    # Classify → route to category handler
    workflow.add_conditional_edges(
        "classify",
        route_after_classify,
        {
            "signer": "signer",
            "contract_reply": "contract_reply",
            "care_report": "care_report",
            "scheduler": "scheduler",
            "skip": "skip",
        },
    )

    # Signer → END (saved to drafts)
    workflow.add_edge("signer", END)

    # Contract reply → review
    workflow.add_edge("contract_reply", "review")

    # Care report → review → auto-send
    workflow.add_edge("care_report", "review")

    # Scheduler → review
    workflow.add_edge("scheduler", "review")

    # Review → route (send or redraft)
    workflow.add_conditional_edges(
        "review",
        route_after_review,
        {
            "send": "send",
            "redraft": "redraft",
            "escalate_draft": "escalate_draft",
        },
    )

    # Redraft → review again
    workflow.add_edge("redraft", "review")

    # Send → END
    workflow.add_edge("send", END)

    # Skip → END
    workflow.add_edge("skip", END)

    # Escalate draft → END
    workflow.add_edge("escalate_draft", END)

    return workflow.compile()


def _redraft_node(state: AgentState) -> dict:
    """Re-route to appropriate drafter based on original classification."""
    category = state.get("classification", {}).get("category", "")
    retry_count = state.get("retry_count", 0) + 1
    logger.info("Redrafting (attempt %d) for category: %s", retry_count, category)

    if category == "contract_inquiry":
        result = nodes.contract_reply_node(state)
    elif category == "reservation":
        result = nodes.scheduler_node(state)
    elif category == "care_record":
        result = nodes.care_report_node(state)
    else:
        result = {}

    result["retry_count"] = retry_count
    return result


def _escalate_draft_node(state: AgentState) -> dict:
    """Save rejected draft to Gmail drafts for manual review."""
    logger.info("Escalating to drafts after review failure...")
    raw = state.get("raw_email", {})
    draft = state.get("draft", {})
    body = draft.get("body", "")

    if body and nodes._sender:
        try:
            nodes._sender.save_draft(raw, body)
            logger.info("Escalated draft saved.")
        except Exception:
            logger.exception("Failed to save escalated draft.")

    nodes.notify(
        title="리뷰 실패 — 임시보관함 확인",
        message=f"보낸이: {raw.get('sender', '')}\n제목: {raw.get('subject', '')}",
    )

    return {"current_step": "escalated", "final_action": "drafted"}
