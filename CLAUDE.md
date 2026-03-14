# AI Mail Agent - CLAUDE.md

## 프로젝트 개요

시니어 개발자 페르소나를 가진 AI 메일 자동 응답 에이전트.
수신 메일을 분석하고, 기술적 질문에 시니어 개발자 관점으로 답변을 작성·발송한다.

## 기술 스택

- **Language**: Python 3.11+
- **Frameworks**: LangChain, LangGraph, AutoGen
- **LLM**: Anthropic Claude (claude-sonnet-4-6 메인)
- **Email**: Gmail API (OAuth 2.0)
- **Vector DB**: ChromaDB (로컬)
- **Task Queue**: Celery + Redis (선택, 스케일 시)
- **Config**: python-dotenv, pydantic-settings

## 디렉토리 구조

```
ai-mail-agent/
├── CLAUDE.md                 # 이 파일
├── USECASE.md                # 유스케이스 문서
├── .env.example              # 환경 변수 템플릿
├── pyproject.toml            # 의존성 관리
├── src/
│   ├── __init__.py
│   ├── main.py               # 엔트리포인트
│   ├── config.py             # 설정 관리
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── classifier.py     # 메일 분류 에이전트
│   │   ├── analyzer.py       # 컨텍스트 분석 에이전트
│   │   ├── drafter.py        # 답변 작성 에이전트
│   │   ├── reviewer.py       # 답변 검토 에이전트
│   │   └── orchestrator.py   # 워크플로우 오케스트레이터
│   ├── graph/
│   │   ├── __init__.py
│   │   ├── workflow.py       # LangGraph 워크플로우 정의
│   │   ├── state.py          # 그래프 상태 정의
│   │   └── nodes.py          # 그래프 노드 함수들
│   ├── mail/
│   │   ├── __init__.py
│   │   ├── gmail_client.py   # Gmail API 클라이언트
│   │   ├── parser.py         # 메일 파싱
│   │   └── sender.py         # 메일 발송
│   ├── rag/
│   │   ├── __init__.py
│   │   ├── embeddings.py     # 임베딩 처리
│   │   ├── vectorstore.py    # ChromaDB 연동
│   │   └── retriever.py      # 검색 로직
│   ├── prompts/
│   │   ├── classifier.txt    # 분류 프롬프트
│   │   ├── drafter.txt       # 답변 작성 프롬프트
│   │   └── reviewer.txt      # 검토 프롬프트
│   └── utils/
│       ├── __init__.py
│       ├── logger.py         # 로깅
│       └── cost_tracker.py   # API 비용 추적
├── tests/
│   ├── __init__.py
│   ├── test_classifier.py
│   ├── test_drafter.py
│   ├── test_workflow.py
│   └── fixtures/
│       └── sample_emails.json
└── scripts/
    ├── setup_gmail.py        # Gmail OAuth 초기 설정
    └── run_agent.py          # 에이전트 실행
```

## 코딩 컨벤션

- Python 타입 힌트 필수
- 함수/클래스 docstring 필수 (Google style)
- 에이전트 간 통신은 Pydantic 모델로 직렬화
- 모든 LLM 호출은 try/except로 감싸고 재시도 로직 포함
- 프롬프트는 코드와 분리하여 prompts/ 디렉토리에 관리
- 환경 변수는 .env 파일로 관리, 절대 하드코딩 금지

## 에이전트 설계 원칙

1. **Single Responsibility**: 각 에이전트는 하나의 역할만 수행
2. **Fail-safe**: 에이전트 실패 시 에스컬레이션 (자동 발송 방지)
3. **Observable**: 모든 판단 과정을 로그로 기록
4. **Cost-aware**: API 호출 비용 추적, 월간 한도 설정
5. **Human-in-the-loop**: 신뢰도 낮은 경우 사람 개입

## 빌드 & 실행

```bash
# 의존성 설치
pip install -e ".[dev]"

# Gmail OAuth 설정
python scripts/setup_gmail.py

# 에이전트 실행
python -m src.main

# 테스트
pytest tests/ -v
```

## 환경 변수

```
ANTHROPIC_API_KEY=         # Claude API 키
GMAIL_CREDENTIALS_PATH=    # Gmail OAuth credentials.json 경로
GMAIL_TOKEN_PATH=          # Gmail token 저장 경로
CHROMA_PERSIST_DIR=        # ChromaDB 저장 경로
AUTO_SEND_THRESHOLD=0.8    # 자동 발송 신뢰도 임계값
POLL_INTERVAL_SECONDS=300  # 메일 폴링 주기 (초)
MAX_MONTHLY_COST_USD=50    # 월간 API 비용 한도
LOG_LEVEL=INFO
```

## 서브에이전트 모델 정책

- 모든 서브에이전트: `claude-sonnet-4-6` (비용 효율)
- 복잡한 아키텍처 판단이 필요한 경우만 opus 에스컬레이션
- 분류(classifier)는 가장 가벼운 작업이므로 haiku 고려 가능
