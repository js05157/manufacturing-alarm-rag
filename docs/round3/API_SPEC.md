# API 명세서

기본 경로는 `/api/v1`이며 실행 후 `/docs`에서 OpenAPI 화면을 확인할 수 있다. 오류 응답은 원격 응답 본문, API 키, traceback을 노출하지 않는다.

## Agent

### POST `/api/v1/chat`

요청:

```json
{
  "message": "다음 주 수원시, 경기도에서 비 없는 평일 오전 공휴일 제외 정비 계획",
  "session_id": "conversation-1"
}
```

응답 주요 필드:

| 필드 | 설명 |
|---|---|
| `session_id` | 실행 로그 식별자 |
| `conversation_id` | 후속 요청 메모리 식별자 |
| `status` | `completed`, `clarification`, `partial`, `failed`, `replan_limit`, `constraint_unavailable` 등 |
| `text` | 사용자 응답 |
| `conditions` | 명시·계승된 조건 |
| `tool_plan`, `tool_results` | 실행 계획과 공통 Tool 응답 |
| `selected_date` | 확정 가능한 첫 날짜 또는 `null` |
| `replan_count`, `exclusion_reasons` | 재계획 근거 |

## Tool

### GET `/api/v1/tools`

등록된 외부·로컬 Tool의 이름, 사용 시점 설명, 입력·출력 Schema를 반환한다.

## 계획

| 메서드 | 경로 | 동작 |
|---|---|---|
| GET | `/api/v1/plans` | 계획 목록 |
| POST | `/api/v1/plans` | 계획 저장과 겹침 목록 반환 |
| GET | `/api/v1/plans/{plan_id}` | 계획 상세 |
| PATCH | `/api/v1/plans/{plan_id}` | 핵심 값 수정과 겹침 목록 반환 |
| DELETE | `/api/v1/plans/{plan_id}` | 계획 삭제 |

POST/PATCH 입력 필드:

- `title`: 필수
- `alarm_code`, `location`, `notes`: 선택
- `plan_date`: `YYYY-MM-DD`, 필수
- `start_time`, `end_time`: `HH:MM`, 필수. 종료가 시작보다 늦어야 한다.
- `session_id`: 생성 근거 실행과 연결할 때 선택

겹치는 계획도 201로 저장하며 `overlaps` 배열에 기존 계획을 반환한다.

## 실행 로그

| 메서드 | 경로 | 동작 |
|---|---|---|
| GET | `/api/v1/logs` | 세션 목록과 이벤트 수 |
| GET | `/api/v1/logs/{session_id}` | 세션과 순서별 전체 이벤트 |
| DELETE | `/api/v1/logs/{session_id}` | 세션과 이벤트 삭제 |

로그 수정 경로는 없다. PATCH/PUT 요청은 405를 반환한다.

## 시스템

### GET `/api/v1/health`

서버 상태와 매뉴얼 SQLite·Vector manifest 준비 여부를 반환한다. 인덱스가 없다고 서버 전체를 중단하지 않으며, RAG Tool 호출 시 `NO_INDEX`로 명시한다.

## 상태 코드

| 코드 | 의미 |
|---|---|
| 200 | 조회·수정 성공 |
| 201 | 계획 저장 성공 |
| 204 | 삭제 성공 |
| 400 | 의미·시간 순서 등 도메인 입력 오류 |
| 404 | 계획·로그 없음 |
| 405 | 허용하지 않는 메서드, 특히 로그 수정 |
| 422 | Pydantic 요청 형식 오류 |
| 500 | 예기치 않은 Agent 실행 실패. 상세는 서버 로그에만 기록 |
| 503 | SQLite 처리 실패 |
