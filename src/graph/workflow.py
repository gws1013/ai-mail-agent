"""LangGraph workflow definition for the mail agent."""

import logging
from langgraph.graph import StateGraph, END
from src.graph.state import AgentState
from src.graph import nodes
from src.agents.classifier import ClassifierAgent
from src.agents.analyzer import AnalyzerAgent
from src.agents.drafter import DrafterAgent
from src.agents.reviewer import ReviewerAgent
from src.mail.gmail_client import GmailClient
from src.mail.sender import EmailSender
from src.rag.vectorstore import VectorStoreManager
from src.rag.retriever import ContextRetriever
from src.config import get_settings

logger = logging.getLogger(__name__)


def route_after_classify(state: AgentState) -> str:
    """Route based on classification result."""
    classification = state.get("classification")
    if not classification:
        return "escalate"

    category = classification.get("category", "needs_human")
    confidence = classification.get("confidence", 0.0)
    settings = get_settings()

    if category == "spam":
        return "skip"
    if category == "needs_human":
        return "escalate"
    if confidence < settings.AUTO_SEND_THRESHOLD:
        return "escalate"
    return "analyze"


def route_after_review(state: AgentState) -> str:
    """Route based on review result."""
    review = state.get("review")
    if not review:
        return "escalate"

    if review.get("approved", False):
        return "send"

    retry_count = state.get("retry_count", 0)
    settings = get_settings()
    if retry_count >= settings.MAX_RETRY_COUNT:
        return "escalate"

    return "redraft"


def increment_retry(state: AgentState) -> dict:
    """Increment retry count before redrafting."""
    return {"retry_count": state.get("retry_count", 0) + 1}


def create_workflow() -> StateGraph:
    """Create and compile the mail agent workflow."""
    settings = get_settings()

    # Initialize components
    gmail_client = GmailClient(
        credentials_path=settings.GMAIL_CREDENTIALS_PATH,
        token_path=settings.GMAIL_TOKEN_PATH,
    )

    vectorstore_mgr = VectorStoreManager(
        persist_directory=settings.CHROMA_PERSIST_DIR,
    )
    retriever = ContextRetriever(vectorstore_manager=vectorstore_mgr)
    sender = EmailSender(gmail_client=gmail_client)

    classifier = ClassifierAgent(api_key=settings.OPENAI_API_KEY)
    analyzer = AnalyzerAgent(api_key=settings.OPENAI_API_KEY, retriever=retriever)
    drafter = DrafterAgent(api_key=settings.OPENAI_API_KEY)
    reviewer = ReviewerAgent(api_key=settings.OPENAI_API_KEY)

    # Inject agents into nodes
    nodes.init_agents(classifier, analyzer, drafter, reviewer, sender, retriever)

    # Build graph
    workflow = StateGraph(AgentState)

    workflow.add_node("classify", nodes.classify_node)
    workflow.add_node("analyze", nodes.analyze_node)
    workflow.add_node("draft", nodes.draft_node)
    workflow.add_node("review", nodes.review_node)
    workflow.add_node("send", nodes.send_node)
    workflow.add_node("escalate", nodes.escalate_node)
    workflow.add_node("skip", nodes.skip_node)
    workflow.add_node("increment_retry", increment_retry)

    # Entry point
    workflow.set_entry_point("classify")

    # Edges
    workflow.add_conditional_edges(
        "classify",
        route_after_classify,
        {
            "analyze": "analyze",
            "escalate": "escalate",
            "skip": "skip",
        },
    )
    workflow.add_edge("analyze", "draft")
    workflow.add_edge("draft", "review")
    workflow.add_conditional_edges(
        "review",
        route_after_review,
        {
            "send": "send",
            "escalate": "escalate",
            "redraft": "increment_retry",
        },
    )
    workflow.add_edge("increment_retry", "draft")
    workflow.add_edge("send", END)
    workflow.add_edge("escalate", END)
    workflow.add_edge("skip", END)

    return workflow.compile()


def process_email(parsed_email: dict, raw_gmail: dict | None = None) -> dict:
    """Process a single email through the workflow.

    Args:
        parsed_email: MailInput-compatible dict with message_id, thread_id, etc.
        raw_gmail: Original Gmail API dict (kept for backward compat in send node).
    """
    app = create_workflow()

    initial_state: AgentState = {
        "raw_email": parsed_email,
        "classification": None,
        "analysis": None,
        "draft": None,
        "review": None,
        "current_step": "start",
        "retry_count": 0,
        "error": None,
        "final_action": "",
    }

    result = app.invoke(initial_state)
    logger.info(f"Workflow complete. Final action: {result.get('final_action')}")
    return result
