# AI Mail Agent - CLAUDE.md

## 프로젝트 개요

요양기관 실무자(사회복지사, 간병인, 요양보호사)를 위한 AI 메일 자동 응답 에이전트.
보호자·시설 관리자와의 이메일을 자동 분류하고, 유형별로 답변 작성·발송 또는 임시보관함 저장을 수행한다.

## 사용자

- 주 사용자: 요양시설 실무자 (사회복지사, 간병인, 요양보호사)
- 수신 대상: 요양중인 어르신의 보호자, 시설 관리자, 외부 문의자

## 기술 스택

- **Language**: Python 3.11+
- **Frameworks**: LangChain, LangGraph
- **LLM**: OpenAI `gpt-5-nano` (기본), `gpt-5.2` (복잡한 답변)
- **Email**: Gmail API (OAuth 2.0) — `credentials/` 디렉토리에 인증 파일 저장
- **Vector DB**: ChromaDB (로컬, 계약서·생활기록 RAG)
- **Config**: python-dotenv, pydantic-settings

## 디렉토리 구조

```
ai-mail-agent/
├── CLAUDE.md                 # 이 파일
├── USECASE.md                # 유스케이스 문서
├── skills.md                 # 에이전트 스킬 정의
├── subagent.md               # 서브에이전트 설계
├── .env                      # 환경 변수 (git 제외)
├── .env.example              # 환경 변수 템플릿
├── .gitignore
├── pyproject.toml             # 의존성 관리
├── credentials/               # Gmail OAuth 인증 파일
│   ├── credentials.json
│   └── token.json
├── data/                      # RAG용 참조 데이터
│   ├── contracts/             # 요양시설 계약서 샘플 (10개)
│   └── care_records/          # 생활기록 보고서 (10명 × 주간)
├── src/
│   ├── __init__.py
│   ├── agent.py               # CLI 엔트리포인트 (-t 파라미터)
│   ├── config.py              # 설정 관리
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── classifier.py      # 메일 분류 에이전트 (softmax)
│   │   ├── signer.py          # 장기요양급여 서명 처리 에이전트
│   │   ├── contract_replier.py # 계약서 기반 자동 답변 에이전트
│   │   ├── care_reporter.py   # 생활기록 보고서 작성 에이전트
│   │   ├── scheduler.py       # 방문 예약 확인 에이전트 (Google Calendar)
│   │   ├── drafter.py         # 범용 답변 작성 에이전트
│   │   └── reviewer.py        # 답변 검토 에이전트
│   ├── graph/
│   │   ├── __init__.py
│   │   ├── workflow.py        # LangGraph 워크플로우 정의
│   │   ├── state.py           # 그래프 상태 정의
│   │   ├── nodes.py           # 그래프 노드 함수들
│   │   └── orchestrator.py    # 멀티 에이전트 오케스트레이션
│   ├── mail/
│   │   ├── __init__.py
│   │   ├── gmail_client.py    # Gmail API 클라이언트
│   │   ├── parser.py          # 메일 파싱
│   │   ├── attachment.py      # 첨부파일 다운로드·처리
│   │   └── sender.py          # 메일 발송·임시보관함 저장
│   ├── rag/
│   │   ├── __init__.py
│   │   ├── embeddings.py      # 임베딩 처리
│   │   ├── vectorstore.py     # ChromaDB 연동
│   │   └── retriever.py       # 계약서·생활기록 검색
│   ├── calendar/
│   │   ├── __init__.py
│   │   └── gcal_client.py     # Google Calendar API (API키 없이 구현)
│   ├── prompts/
│   │   ├── classifier.txt
│   │   ├── signer.txt
│   │   ├── contract_replier.txt
│   │   ├── care_reporter.txt
│   │   ├── scheduler.txt
│   │   └── reviewer.txt
│   └── utils/
│       ├── __init__.py
│       ├── logger.py          # 로깅
│       ├── notifier.py        # 윈도우 알림
│       └── cost_tracker.py    # API 비용 추적
├── tests/
│   ├── __init__.py
│   ├── test_classifier.py
│   ├── test_workflow.py
│   └── fixtures/
│       └── sample_emails.json
└── logs/
    └── (런타임 생성)
```

## 코딩 컨벤션

- 유지보수가 쉬운 클린 코드 스타일
- 가독성 우선, 읽기 쉬운 변수·함수명 사용
- Python 타입 힌트 필수
- 함수/클래스 docstring 필수 (Google style)
- 시간 복잡도를 고려한 구현
- 에이전트 간 통신은 Pydantic 모델로 직렬화
- 모든 LLM 호출은 try/except + 재시도 로직 포함
- 프롬프트는 코드와 분리하여 `prompts/` 디렉토리에 관리
- 환경 변수는 `.env` 파일로 관리, 절대 하드코딩 금지

## 에이전트 설계 원칙

1. **Single Responsibility**: 각 에이전트는 하나의 역할만 수행
2. **Fail-safe**: 에이전트 실패 시 임시보관함 저장 (자동 발송 방지)
3. **Observable**: 모든 판단 과정을 로그로 기록 (softmax 확률 포함)
4. **Cost-aware**: API 호출 비용 추적, 월간 한도 설정
5. **Human-in-the-loop**: 서명·생활기록 등 확인 필요 항목은 임시보관함 저장
6. **Multi-agent Orchestration**: LangGraph 기반 오케스트레이션 노드 포함

## 빌드 & 실행

```bash
# 의존성 설치
pip install -e ".[dev]"

# 에이전트 실행 (현재 시점 이후 메일만 처리)
py -3.11 agent.py -t 0

# 에이전트 실행 (1시간 전 메일부터 처리)
py -3.11 agent.py -t 1

# 테스트
pytest tests/ -v
```

## 환경 변수

```
OPENAI_API_KEY=            # OpenAI API 키
GMAIL_CREDENTIALS_PATH=    # Gmail OAuth credentials.json 경로
GMAIL_TOKEN_PATH=          # Gmail token 저장 경로
CHROMA_PERSIST_DIR=        # ChromaDB 저장 경로
POLL_INTERVAL_SECONDS=10   # 메일 폴링 주기 (초)
MAX_MONTHLY_COST_USD=50    # 월간 API 비용 한도
LOG_LEVEL=INFO
```

## 서브에이전트 모델 정책

- 기본 모든 에이전트: `gpt-5-nano` (비용 효율)
- 복잡한 답변 필요 시: `gpt-5.2`로 에스컬레이션
