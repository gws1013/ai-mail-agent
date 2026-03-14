"""Multi-agent orchestrator — initialises agents and runs the workflow."""

from __future__ import annotations

import logging
from typing import Any

from src.config import get_settings
from src.agents.classifier import ClassifierAgent
from src.agents.signer import SignerAgent
from src.agents.contract_replier import ContractReplierAgent
from src.agents.care_reporter import CareReporterAgent
from src.agents.scheduler import SchedulerAgent
from src.agents.reviewer import ReviewerAgent
from src.calendar.gcal_client import GoogleCalendarClient
from src.mail.gmail_client import GmailClient
from src.mail.sender import EmailSender
from src.rag.vectorstore import VectorStoreManager
from src.rag.retriever import ContextRetriever
from src.graph import nodes
from src.graph.workflow import build_workflow

logger = logging.getLogger(__name__)


class Orchestrator:
    """Initialise all agents and manage workflow execution.

    Args:
        gmail_client: Authenticated GmailClient.
    """

    def __init__(self, gmail_client: GmailClient) -> None:
        settings = get_settings()
        api_key = settings.OPENAI_API_KEY

        # RAG
        self._store_manager = VectorStoreManager(settings.CHROMA_PERSIST_DIR)
        self._retriever = ContextRetriever(self._store_manager)

        # Agents
        self._classifier = ClassifierAgent(api_key)
        self._signer = SignerAgent(api_key)
        self._contract_replier = ContractReplierAgent(api_key)
        self._care_reporter = CareReporterAgent(api_key)
        self._scheduler = SchedulerAgent(
            api_key,
            GoogleCalendarClient(),  # Mock mode (no API key)
        )
        self._reviewer = ReviewerAgent(api_key)

        # Mail
        self._gmail_client = gmail_client
        self._sender = EmailSender(gmail_client)

        # Inject into nodes
        nodes.init_agents(
            classifier=self._classifier,
            signer=self._signer,
            contract_replier=self._contract_replier,
            care_reporter=self._care_reporter,
            scheduler=self._scheduler,
            reviewer=self._reviewer,
            sender=self._sender,
            retriever=self._retriever,
            gmail_client=gmail_client,
        )

        # Build workflow
        self._workflow = build_workflow()
        logger.info("Orchestrator initialised — all agents ready.")

    def ingest_data(self) -> None:
        """Ingest PDF data into vector store for RAG."""
        logger.info("Ingesting contract PDFs...")
        n_contracts = self._store_manager.ingest_pdf_directory(
            "contracts", "data/contracts"
        )
        logger.info("Ingested %d contract chunks.", n_contracts)

        logger.info("Ingesting care record PDFs...")
        n_care = self._store_manager.ingest_pdf_directory(
            "care_records", "data/care_records"
        )
        logger.info("Ingested %d care record chunks.", n_care)

    def process_email(self, raw_email: dict[str, Any]) -> dict[str, Any]:
        """Run the full workflow for a single email.

        Args:
            raw_email: Raw email dict from GmailClient.

        Returns:
            Final workflow state.
        """
        initial_state = {
            "raw_email": raw_email,
            "classification": None,
            "analysis": None,
            "attachments": [],
            "signer_result": None,
            "draft": None,
            "care_report": None,
            "scheduler_result": None,
            "review": None,
            "current_step": "start",
            "final_action": "",
            "error": None,
            "retry_count": 0,
        }

        try:
            result = self._workflow.invoke(initial_state)
            logger.info(
                "Email processed: action=%s step=%s",
                result.get("final_action", "unknown"),
                result.get("current_step", "unknown"),
            )
            return result
        except Exception as e:
            logger.exception("Workflow failed for email: %s", raw_email.get("subject"))
            return {**initial_state, "error": str(e), "final_action": "error"}
