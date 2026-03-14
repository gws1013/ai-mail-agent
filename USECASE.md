# AI Mail Agent - 유스케이스 문서

## 시스템 개요

```
┌─────────────────────────────────────────────────────────┐
│                    AI Mail Agent                         │
│                                                          │
│  [Gmail API] ──> [Mail Watcher] ──> [LangGraph Router]  │
│                                          │               │
│                    ┌─────────────────────┼───────┐       │
│                    │                     │       │       │
│               [Classifier]        [Analyzer] [Ignore]   │
│                    │                     │               │
│               [Reply Draft]        [Context RAG]        │
│                    │                     │               │
│               [Review Agent]  <──────────┘               │
│                    │                                     │
│               [Gmail Send]                               │
│                    │                                     │
│               [Slack Notify] (optional)                  │
└─────────────────────────────────────────────────────────┘
```

## 메인 시나리오 (Happy Path)

### UC-1: 기술 질문 메일 자동 답변

**트리거**: 새 메일 수신 (Gmail API Push/Poll)

**흐름**:
1. Mail Watcher가 새 메일 감지
2. Classifier Agent가 메일 분류
   - 기술 질문 / 코드 리뷰 요청 / 버그 리포트 / 일반 업무 / 스팸·무시
3. Analyzer Agent가 메일 내용 심층 분석
   - 기술 스택 파악
   - 질문 핵심 추출
   - 관련 컨텍스트 RAG 검색 (과거 메일, 문서)
4. Reply Drafter Agent가 시니어 개발자 톤으로 답변 초안 작성
   - 기술적 정확성 우선
   - 코드 예시 포함
   - 친절하지만 간결한 톤
5. Review Agent가 답변 검토
   - 기술적 오류 체크
   - 톤 적절성 확인
   - 민감 정보 포함 여부 확인
6. 자동 발송 또는 사용자 승인 후 발송

### UC-2: 코드 리뷰 요청 메일 처리

**트리거**: 메일 제목/본문에 코드 리뷰 관련 키워드

**흐름**:
1. 메일에 포함된 코드 추출
2. 코드 분석 (언어 감지, 패턴 분석)
3. 리뷰 코멘트 작성 (버그, 성능, 가독성, 보안)
4. 시니어 개발자 관점의 피드백 포함하여 답변

### UC-3: 무시할 메일 필터링

**트리거**: 스팸, 마케팅, 자동 알림 메일

**흐름**:
1. Classifier가 "무시" 분류
2. 라벨링만 하고 답변하지 않음
3. 로그 기록

### UC-4: 에스컬레이션 (사람 개입 필요)

**트리거**: 에이전트가 확신 없는 메일, 민감한 내용

**흐름**:
1. 분류 신뢰도가 낮거나 민감 키워드 감지
2. 초안만 작성하고 자동 발송하지 않음
3. Slack/이메일로 사용자에게 리뷰 요청 알림

## 에이전트 구성

### LangGraph 워크플로우

```
START
  │
  ▼
[poll_mail] ──새 메일 없음──> [wait] ──> [poll_mail]
  │
  새 메일 있음
  │
  ▼
[classify_mail]
  │
  ├── spam/ignore ──> [label_and_skip] ──> END
  │
  ├── needs_human ──> [escalate] ──> END
  │
  └── auto_reply ──> [analyze_context]
                        │
                        ▼
                   [draft_reply]
                        │
                        ▼
                   [review_reply]
                        │
                        ├── rejected ──> [draft_reply] (재작성)
                        │
                        └── approved ──> [send_reply] ──> END
```

### AutoGen 멀티에이전트 구성

| Agent | Role | Model |
|-------|------|-------|
| Classifier | 메일 분류 | claude-sonnet-4-6 |
| Analyzer | 컨텍스트 분석 + RAG | claude-sonnet-4-6 |
| Drafter | 답변 초안 작성 | claude-sonnet-4-6 |
| Reviewer | 품질 검토 | claude-sonnet-4-6 |
| Orchestrator | 전체 워크플로우 관리 | claude-sonnet-4-6 |

## 비기능 요구사항

- **폴링 주기**: 5분 (Gmail API 쿼터 고려)
- **답변 시간**: 메일 수신 후 10분 이내
- **자동 발송 정책**: 신뢰도 80% 이상만 자동, 나머지는 사용자 승인
- **로깅**: 모든 에이전트 판단 과정 기록
- **비용 제한**: 월 API 호출 한도 설정
