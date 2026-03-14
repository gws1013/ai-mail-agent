# AI Mail Agent

요양원(시니어 케어) 수신 메일을 자동 분류하고 답변을 작성·발송하는 AI 에이전트.

## 주요 기능

- **메일 자동 분류** — 서명 요청, 계약 문의, 생활기록 요청, 방문 예약, 스팸 5개 카테고리
- **카테고리별 전문 에이전트** — 서명 처리, 계약 답변, 생활기록 보고서, 예약 확인
- **RAG 기반 컨텍스트 검색** — ChromaDB 벡터스토어에서 계약서/생활기록 PDF 검색
- **자동 발송 + 리뷰** — 리뷰어 에이전트 검토 후 자동 발송, 실패 시 임시보관함 저장
- **PDF 첨부** — 생활기록 요청 시 해당 어르신 PDF 파일 자동 첨부
- **데스크톱 알림** — 자동 발송/임시보관함 저장 시 Windows 알림

## 아키텍처

```
Gmail 수신 → 분류(Classifier) → 카테고리별 에이전트 → 리뷰(Reviewer) → 자동 발송
                                    ↓
                    ┌───────────────┼───────────────┐───────────────┐
                  서명처리       계약답변        생활기록보고서     예약확인
                (Signer)   (ContractReplier)  (CareReporter)   (Scheduler)
```

LangGraph StateGraph 기반 워크플로우로 노드 간 상태를 공유합니다.

## 기술 스택

| 구분 | 기술 |
|------|------|
| Language | Python 3.11+ |
| Workflow | LangGraph (StateGraph) |
| LLM | OpenAI gpt-4o-mini |
| Email | Gmail API (OAuth 2.0) |
| Vector DB | ChromaDB (로컬) |
| Embeddings | HuggingFace all-MiniLM-L6-v2 |
| Notification | plyer (Windows) |

## 설치 및 실행

```bash
# 의존성 설치
pip install -e ".[dev]"

# 환경 변수 설정
cp .env.example .env
# .env 파일에 OPENAI_API_KEY 등 입력

# Gmail OAuth 설정
# credentials/ 디렉토리에 credentials.json 배치 후 최초 실행 시 브라우저 인증

# 실행
py -3.11 agent.py -t 1    # 1시간 전부터 메일 처리
py -3.11 agent.py -t 0    # 지금부터 새 메일만 처리
```

## 디렉토리 구조

```
ai-mail-agent/
├── agent.py                  # CLI 엔트리포인트
├── src/
│   ├── agents/               # 분류·서명·계약·생활기록·예약·리뷰 에이전트
│   ├── graph/                # LangGraph 워크플로우, 노드, 상태 정의
│   ├── mail/                 # Gmail API 클라이언트, 파싱, 발송
│   ├── rag/                  # ChromaDB 벡터스토어, 임베딩, 검색
│   ├── prompts/              # LLM 프롬프트 템플릿 (txt)
│   └── utils/                # 로깅, 비용 추적, 알림
├── data/care_records/        # 생활기록 PDF 파일
├── credentials/              # Gmail OAuth 인증 파일
└── .env                      # 환경 변수
```

## 환경 변수

| 변수 | 설명 |
|------|------|
| `OPENAI_API_KEY` | OpenAI API 키 |
| `GMAIL_CREDENTIALS_PATH` | Gmail OAuth credentials.json 경로 |
| `GMAIL_TOKEN_PATH` | Gmail token 저장 경로 |
| `CHROMA_PERSIST_DIR` | ChromaDB 저장 경로 |
| `POLL_INTERVAL_SECONDS` | 메일 폴링 주기 (초) |
| `MAX_MONTHLY_COST_USD` | 월간 API 비용 한도 |
| `LOG_LEVEL` | 로그 레벨 (INFO, DEBUG 등) |

## 라이선스

Private project.
