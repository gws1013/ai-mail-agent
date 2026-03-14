"""PDF 데이터를 ChromaDB에 인제스트하는 스크립트.

data/contracts/ 와 data/care_records/ 의 PDF 파일을 읽어
ChromaDB 벡터 스토어에 저장한다.
"""

from __future__ import annotations

import sys
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.rag.vectorstore import VectorStoreManager


def main() -> None:
    persist_dir = str(ROOT / "chroma_db")
    store = VectorStoreManager(persist_dir=persist_dir)

    print("=== contracts 컬렉션 인제스트 ===")
    n_contracts = store.ingest_pdf_directory("contracts", str(ROOT / "data" / "contracts"))
    print(f"  → {n_contracts}개 청크 저장 완료")

    print()
    print("=== care_records 컬렉션 인제스트 ===")
    n_care = store.ingest_pdf_directory("care_records", str(ROOT / "data" / "care_records"))
    print(f"  → {n_care}개 청크 저장 완료")

    print()
    print(f"ChromaDB 저장 경로: {persist_dir}")
    print("인제스트 완료!")


if __name__ == "__main__":
    main()
