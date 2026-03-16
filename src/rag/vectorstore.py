"""ChromaDB vector store manager for contract and care record data."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from src.rag.embeddings import get_embedding_function

logger = logging.getLogger(__name__)


class VectorStoreManager:
    """Manage ChromaDB collections for RAG search.

    Args:
        persist_dir: Directory for ChromaDB storage.
    """

    def __init__(self, persist_dir: str = "./chroma_db") -> None:
        self._persist_dir = persist_dir
        self._collections: dict[str, Any] = {}

    def get_or_create_collection(self, name: str) -> Any:
        """Get or create a Chroma collection.

        Args:
            name: Collection name (e.g. 'contracts', 'care_records').

        Returns:
            LangChain Chroma instance.
        """
        if name not in self._collections:
            try:
                from langchain_chroma import Chroma
            except ImportError:
                from langchain_community.vectorstores import Chroma

            self._collections[name] = Chroma(
                collection_name=name,
                embedding_function=get_embedding_function(),
                persist_directory=self._persist_dir,
            )
            logger.info("Chroma collection '%s' ready.", name)

        return self._collections[name]

    def ingest_pdf_directory(self, name: str, pdf_dir: str) -> int:
        """Load all PDFs from a directory into a collection.

        Args:
            name: Collection name.
            pdf_dir: Directory containing PDF files.

        Returns:
            Number of documents ingested.
        """
        from langchain_community.document_loaders import PyPDFLoader
        from langchain_text_splitters import RecursiveCharacterTextSplitter

        pdf_path = Path(pdf_dir)
        if not pdf_path.exists():
            logger.warning("PDF directory not found: %s", pdf_dir)
            return 0

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200,
        )

        all_docs = []
        for pdf_file in sorted(pdf_path.glob("*.pdf")):
            try:
                loader = PyPDFLoader(str(pdf_file))
                pages = loader.load()
                chunks = splitter.split_documents(pages)
                for chunk in chunks:
                    chunk.metadata["source_file"] = pdf_file.name
                all_docs.extend(chunks)
                logger.debug("Loaded %d chunks from %s", len(chunks), pdf_file.name)
            except Exception:
                logger.exception("Failed to load PDF: %s", pdf_file)

        if all_docs:
            collection = self.get_or_create_collection(name)
            existing = collection.get()
            if existing and existing.get("ids"):
                logger.info(
                    "Collection '%s' already has %d documents — skipping ingest.",
                    name, len(existing["ids"]),
                )
                return 0
            collection.add_documents(all_docs)
            logger.info(
                "Ingested %d documents into collection '%s'.",
                len(all_docs), name,
            )

        return len(all_docs)
