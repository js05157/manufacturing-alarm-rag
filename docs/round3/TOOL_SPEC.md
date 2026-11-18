# Tool 정의서

## 1. 공통 계약

성공:

```json
{"ok": true, "data": {}}
```

실패:

```json
{"ok": false, "error": {"code": "TIMEOUT", "message": "외부 API 응답 시간이 초과되었습니다.", "retryable": true}}
```

Tool 구현은 네트워크 예외와 응답 파싱 오류를 밖으로 던지지 않는다. API 키, 요청 헤더, 원격 오류 본문은 실패 메시지에 포함하지 않는다.

## 2. 외부 API Tool

### search_maintenance_location

- 사용 시점: 사용자가 날씨 조건이 있는 정비 지역 이름을 말했지만 좌표가 없을 때
- 출처: Open-Meteo Geocoding API / GeoNames
- 입력: `query`(필수), `country_code`(기본 `KR`), `count`(1~10, 기본 5)
- 출력: 위치 ID, 이름, 행정구역, 국가, 위·경도, 고도, 시간대, 인구
- 주의: 후보가 여러 개면 `ambiguous=true`를 반환한다. Agent는 시·도까지 일치하는 단일 후보가 아니면 임의 선택하지 않는다.

### get_maintenance_weather

- 사용 시점: 사용자가 강수 조건을 지정한 정비 일정을 요청했을 때
- 출처: MET Norway Locationforecast 2.0
- 입력: `latitude`, `longitude`, `timezone`
- 출력: 예보 갱신 시각, 단위, 날짜별 시계열의 시각·기온·풍속·강수량·기상 코드
- 주의: 실제 HTTP 요청 좌표는 소수 4자리로 제한한다. 값이 없는 시간대는 `None`을 유지하며 0으로 바꾸지 않는다.

### get_public_holidays

- 사용 시점: 사용자가 공휴일 제외를 명시했을 때
- 출처: Nager.Date Community REST API v4
- 입력: `year`, `country_code`(기본 `KR`), 선택적 `start_date`, `end_date`
- 출력: 날짜, 영문 명칭, 전국 공휴일 여부, 적용 하위 행정구역, 공휴일 유형
- 주의: 원문 API가 주지 않는 한국어 이름을 만들지 않는다.

## 3. 로컬 서버 API Tool

### search_fr_e800_manual

- 사용 시점: FR-E800 알람 원인·점검·대처 또는 설비 증상의 제조사 근거가 필요할 때
- 입력: `question`
- 출력: 검증된 답변, evidence ID, 매뉴얼명, PDF 실제 페이지, 문서 내부 페이지, 검증 결과
- 데이터: 기존 2회차에서 구축한 SQLite·Chroma만 사용한다.
- 동작: `evidence_only=True`로 전체 필수 점검·대처와 페이지를 프로그램이 복원·검증한다.
- 색인 없음: `NO_INDEX`
- 근거 없음: `NO_EVIDENCE`
- 원본 불일치: `INDEX_ERROR`

## 4. 실패 코드

| 코드 | 의미 | 재시도 |
|---|---|---|
| `INVALID_INPUT` | 필수 인자 누락·형식·범위 오류 | 아니오 |
| `NO_RESULT` | 위치 후보 없음 | 인자를 바꿀 때만 |
| `AMBIGUOUS_LOCATION` | 위치 후보를 하나로 확정할 수 없음 | 사용자 확인 필요 |
| `NO_FORECAST` | 해당 위치 예보 없음 | 날짜·위치 변경 시 |
| `TIMEOUT` | 응답 시간 초과 | 가능 |
| `CONNECTION_ERROR` | 연결 실패 | 가능 |
| `REQUEST_ERROR` | 기타 요청 실패 | 가능 |
| `HTTP_ERROR` | 원격 HTTP 오류 | 429·5xx만 가능 |
| `INVALID_RESPONSE` | JSON 또는 응답 구조 불일치 | 아니오 |
| `NO_INDEX` | 로컬 RAG 인덱스 없음 | 구축 후 가능 |
| `INDEX_ERROR` | DB·Vector 원본 또는 모델 불일치 | 재구축 필요 |
| `NO_EVIDENCE` | 검증된 FR-E800 근거 없음 | 질문 변경 시 |
| `RAG_ERROR` | RAG 처리 실패 | 원인 확인 필요 |
| `TOOL_NOT_FOUND` | 미등록 Tool | 아니오 |

## 5. 등록·확장

Tool은 `ToolSpec`과 `invoke(**kwargs) -> ToolResult`를 구현한 뒤 `ToolRegistry.register`에 등록한다. Agent에는 이름, 언제 쓰는지 설명, 입력·출력 JSON Schema만 노출한다. 계획 저장처럼 이미 정해진 값을 CRUD하는 작업은 Tool로 만들지 않고 저장소와 API가 처리한다.
