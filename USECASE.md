# AI Mail Agent - 유스케이스 문서

## 시스템 개요

```
┌──────────────────────────────────────────────────────────────────┐
│                      AI Mail Agent                               │
│                                                                  │
│  [Gmail API] ──10초 폴링──> [Mail Watcher] ──시간순 정렬──>     │
│                                    │                             │
│                              [Classifier]                        │
│                           (softmax 분류)                         │
│                    ┌──────┬────┼────┬──────┐                     │
│                    │      │    │    │      │                     │
│                    ▼      ▼    ▼    ▼      ▼                     │
│              [서명처리] [계약답변] [생활기록] [예약확인] [스팸]   │
│                 │        │       │        │       │              │
│              임시보관  자동발송  임시보관  자동발송  무시          │
│                 │        │       │        │                      │
│              [윈도우 알림] ◄──────┘                              │
└──────────────────────────────────────────────────────────────────┘
```

## 메일 분류 카테고리

| 카테고리 | 설명 | 처리 방식 |
|----------|------|-----------|
| `signature_request` | 장기요양급여 확인 서명 요청 | 첨부파일 다운로드 → 서명 삽입 → **임시보관함** 저장 |
| `contract_inquiry` | 계약서 내용 관련 보호자 문의 | RAG로 계약서 검색 → **자동 답변 발송** |
| `care_record` | 생활기록 보고서 관련 메일 | 생활기록 데이터 조회 → 보고서 작성 → **임시보관함** 저장 |
| `reservation` | 요양시설 방문 예약·자리 문의 | Google Calendar 확인 → **자동 답변 발송** |
| `spam_or_other` | 스팸·광고·기타 무관 메일 | 답장 없음, 임시보관함 저장 없음 |

---

## UC-1: 장기요양급여 확인 서명 요청 처리

**트리거**: 보호자 또는 관련 기관이 장기요양급여 확인 서명을 요청하는 메일 수신

**흐름**:
1. Classifier가 `signature_request`로 분류 (softmax 확률 로깅)
2. 첨부파일 다운로드
3. Signer Agent가 해당 파일에 서명 삽입
4. 서명된 파일을 첨부한 답장을 **임시보관함에 저장** (사람 확인 필요)
5. 윈도우 알림으로 사용자에게 확인 요청

**임시보관함 저장 사유**: 서명이 올바른 고객 파일에 정확히 포함되었는지 사람의 확인 필수

---

## UC-2: 계약서 내용 관련 보호자 문의 답변

**트리거**: 보호자가 요양시설 계약서 내용에 대해 문의하는 메일 수신

**흐름**:
1. Classifier가 `contract_inquiry`로 분류
2. RAG에서 관련 계약서 내용 검색 (ChromaDB)
3. Contract Replier Agent가 계약서 기반 답변 초안 작성
4. Reviewer Agent가 답변 검토 (정확성, 톤)
5. 검토 통과 시 **자동 발송**
6. 윈도우 알림으로 발송 완료 통보

**참조 데이터**: `data/contracts/` 디렉토리에 요양시설 계약서 10개 저장

---

## UC-3: 생활기록 보고서 관련 메일 처리

**트리거**: 보호자 또는 시설장이 요양 중인 어르신의 생활기록을 요청하는 메일 수신

**흐름**:
1. Classifier가 `care_record`로 분류
2. Care Reporter Agent가 해당 어르신의 생활기록 데이터 조회
   - 체중, 식사, 수면, 활동, 건강 상태 등
3. 보고서 형태로 답변 작성
4. 보호자 정보가 정확한지 확인 필요 → **임시보관함에 저장**
5. 윈도우 알림으로 사용자에게 확인 요청

**참조 데이터**: `data/care_records/` 디렉토리에 10명 × 주간 기록 저장

---

## UC-4: 요양시설 방문 예약·자리 문의 답변

**트리거**: 외부 문의자가 요양시설 자리 여부, 방문 예약 가능 여부를 문의하는 메일 수신

**흐름**:
1. Classifier가 `reservation`으로 분류
2. Scheduler Agent가 Google Calendar에서 일정 확인
3. 자리 현황·방문 가능 일정을 포함한 답변 작성
4. **자동 발송**
5. 윈도우 알림으로 발송 완료 통보

**구현 참고**: Google Calendar API 키 없이 인터페이스만 구현 (나중에 연동)

---

## UC-5: 스팸·기타 메일 무시

**트리거**: 광고, 뉴스레터, 자동 알림 등 업무 무관 메일 수신

**흐름**:
1. Classifier가 `spam_or_other`로 분류
2. 답장하지 않음
3. 임시보관함에 저장하지 않음
4. 분류 로그만 기록

---

## 에이전트 구성

### LangGraph 오케스트레이션 워크플로우

```
START
  │
  ▼
[poll_mail] ──새 메일 없음──> [wait 10초] ──> [poll_mail]
  │
  새 메일 있음 (시간순 정렬, 가장 오래된 것부터)
  │
  ▼
[classify_mail] ──softmax 확률 로깅──>
  │
  ├── signature_request ──> [download_attachment]
  │                              │
  │                         [sign_document]
  │                              │
  │                         [save_to_drafts] ──> [notify_user] ──> END
  │
  ├── contract_inquiry ──> [rag_search_contract]
  │                              │
  │                         [draft_reply]
  │                              │
  │                         [review_reply]
  │                              │
  │                         ├── rejected ──> [draft_reply] (재작성)
  │                         └── approved ──> [send_reply] ──> [notify_user] ──> END
  │
  ├── care_record ──> [fetch_care_data]
  │                        │
  │                   [draft_report]
  │                        │
  │                   [save_to_drafts] ──> [notify_user] ──> END
  │
  ├── reservation ──> [check_calendar]
  │                        │
  │                   [draft_reply]
  │                        │
  │                   [send_reply] ──> [notify_user] ──> END
  │
  └── spam_or_other ──> [log_and_skip] ──> END
```

### 서브에이전트 구성

| Agent | Role | Model | 출력 |
|-------|------|-------|------|
| Classifier | 메일 분류 (softmax) | gpt-5-nano | 카테고리 + 확률 분포 |
| Signer | 서명 파일 처리 | gpt-5-nano | 서명 삽입된 파일 |
| Contract Replier | 계약서 기반 답변 | gpt-5-nano | 답변 본문 |
| Care Reporter | 생활기록 보고서 | gpt-5-nano | 보고서 본문 |
| Scheduler | 캘린더 확인·답변 | gpt-5-nano | 예약 안내 답변 |
| Reviewer | 답변 품질 검토 | gpt-5-nano | 승인/거부 + 피드백 |
| Orchestrator | 워크플로우 관리 | — | 노드 라우팅 |

## CLI 실행 옵션

```bash
# 현재 시점 이후 메일만 처리
py -3.11 agent.py -t 0

# 1시간 전 메일부터 처리
py -3.11 agent.py -t 1

# 3시간 전 메일부터 처리
py -3.11 agent.py -t 3
```

## 비기능 요구사항

- **폴링 주기**: 10초마다 수시 확인
- **메일 정렬**: 시점 기준 가장 오래된 메일부터 처리
- **중복 방지**: 이미 답장한 메일에는 재답장하지 않음
- **알림**: 답장 또는 임시보관함 저장 시 윈도우 알림
- **시점 파라미터**: `-t N` 으로 N시간 전 메일부터 처리
- **백그라운드 실행**: 항상 실행 상태 유지
- **특정 시간 실행**: 특정 시간 동안만 실행되는 기능 포함
- **로깅**: 분류 결과 softmax 확률 포함 전체 로깅
- **비용 제한**: 월 API 호출 한도 설정
