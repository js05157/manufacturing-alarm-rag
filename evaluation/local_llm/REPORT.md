# Qwen3 4B 로컬 통합 검증

실행: 2026-10-27T00:02:23.676138+09:00

## 모델과 서버

- GGUF: `C:\AI\models\qwen3-4b\Qwen3-4B-Q4_K_M.gguf` · 2,497,280,256바이트
- SHA-256: `7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5`
- 다운로드 폴더의 같은 모델 파일 존재: False
- llama.cpp `b11900-74b104c9b`, 모델 alias `qwen3-4b`
- 시작 스크립트 기본 구성: 127.0.0.1:8080, CPU 최대 6개 물리 코어(Threads 옵션), GPU layers 0, parallel 1
- 컨텍스트 4096, 생성 상한 512, temperature 0.2, seed 42
- /no_think, enable_thinking=false, reasoning off 사용. 모델·E5는 로컬 파일만 사용하며 외부 LLM 호출 없음.

## 실제 Qwen 추론

단독 한국어 생성: 4.497초, 입력 49토큰, 출력 46토큰, 한국어 확인=True.

| 사례 | 실제 LLM 호출 수 | 전체 응답 시간 | 입력 토큰 | 출력 토큰 | 상태 | 근거 검사 |
|---|---:|---:|---|---|---|---|
| code | 1 | 10.783초 | [2515] | [80] | evidence | 통과 |
| mixed | 1 | 6.912초 | [1205] | [67] | evidence | 통과 |
| symptom | 1 | 24.518초 | [720] | [167] | evidence | 통과 |
| fan_noise | 1 | 17.127초 | [1409] | [148] | evidence | 통과 |
| unsupported | 1 | 1.756초 | [2521] | [12] | unconfirmed | 통과 |
| unknown | 0 | 0.002초 | [] | [] | insufficient | 통과 |

실제 LLM을 호출한 RAG 사례의 평균 전체 응답 시간: **12.219초**.
서버는 이미 로드된 상태이며 prompt/KV 캐시를 사용한다. 답변 문자열 캐시는 사용하지 않는다. E5는 한 번 예열했다. 단독·RAG 수치는 단일 실행 사례의 측정값으로, 브라우저 렌더링과 모델 최초 로딩을 제외한다. 초기 실행이나 캐시 상태가 다른 요청은 더 오래 걸릴 수 있다.

Qwen의 응답은 실제 llama.cpp API의 모델명과 토큰 사용량을 검증했다. 모의 응답으로 이 표를 계산하지 않았다. unknown 사례는 미등록 코드로 사전 중단되어 LLM을 호출하지 않았다.

## 검색 성능과 답변 정확도 구분

- 기존 Hit@3: 90% (9/10). 이번 동일 40문항 검색 회귀: 90% (10개 대상), 코드 없는 자연어 5개 제외.
- 기존 부족 전압 자연어 질의의 검색 실패는 남아 있다. 이번 통합에서 검색 지표를 개선했다고 주장하지 않는다.
- 위 사례의 근거·출처·필수 목록 검사는 전체 40문항 LLM 답변 정답률을 뜻하지 않는다. **전체 40문항 로컬 LLM 정답률은 미측정**이다.
- 기존 추출형 생성 계약을 유지한다. Qwen이 한국어 원문 근거를 선택해 생성하고 프로그램이 필수 목록을 보완한다. 자유로운 진단 문장의 의미적 정답을 보장하지 않는다.

## 실패 처리와 회귀 검사

- 실제 로컬 토크나이저로 4096토큰 초과 요청 차단: True
- 실제 미사용 loopback 포트의 연결 실패 처리: True
- 여러 요청으로 나누는 원문 항목 단위 분할, HTTP 오류, 잘린 생성, 잘못된 JSON, 비어 있는 답변, 서버 모델 불일치, 외부 API로 자동 전환하지 않는 처리는 모의 테스트에서 검사한다.
- Windows 시작 스크립트의 파일 누락 및 다른 프로세스의 포트 점유 오류도 검사한다. 실행 중인 프로세스를 종료하지 않는다.
- 최근 전체 pytest JUnit 기록: 78개, 실패 0, 오류 0, 건너뜀 0.
- 실제 Streamlit→로컬 Qwen 연결: 예외 없음=True, 오류 없음=True, PDF 출처=True, 로컬 생성 시간 표시=True, 대화 기록 유지=True.

## 원본 보존

- 기존 Chroma 컬렉션 `e800_eee4c84748796e8d`, 224개 청크 재사용. 재색인 없음.
- 문서·메타데이터·임베딩 전체 지문 일치: True
- 컬렉션 지문: `9caa34998d38154f7b93f090a77ae8a2140c3a16f14709436a9f8f11f20494ae`
- `storage/alarms.db` SHA-256 보존: True
- `storage/chroma/manifest.json` SHA-256 보존: True
- `evaluation/questions.json` SHA-256 보존: True
- `evaluation/results.json` SHA-256 보존: True
- `evaluation/results.csv` SHA-256 보존: True
- `evaluation/REPORT.md` SHA-256 보존: True

## 미완료·한계

- 전체 40문항 실제 로컬 LLM 정답률과 반복 실행 p50/p95는 미측정이다.
- 실제 사례는 모두 한 요청에 들어갔다. 복수 요청 분할은 모의 검증이며 실제 대규모 다중 알람 생성 성능으로 해석하지 않는다.
- CPU 추론은 긴 프롬프트에서 지연이 크며 서버 prompt/KV 캐시 상태에 따라 시간이 달라진다.
- 이 보고서에는 원문 대량 데이터·전체 답변을 포함하지 않는다. 상세 결과는 Git에서 제외된 smoke/results.json, ui.json, retrieval_regression/results.json에 보존한다.

## 변경 파일

- 설정·UI·의존성: `.env.example`, `.gitignore`, `config.py`, `app.py`, `requirements.txt`
- 서버·전송·생성: `scripts/start_llm.ps1`, `rag/local_llm.py`, `rag/local_answer_generator.py`, `rag/pipeline.py`
- 근거 순서·검증·오프라인 검색: `rag/answer_generator.py`, `rag/answer_validator.py`, `rag/embeddings.py`, `rag/vector_retriever.py`, `rag/router.py`
- 검증·문서: `evaluation/evaluate.py`, `evaluation/validate_local.py`, `evaluation/local_llm/REPORT.md`, `evaluation/local_llm/retrieval_regression/REPORT.md`, `README.md`
- 테스트: `tests/test_local_llm.py`, `tests/test_start_llm.py`, `tests/test_app.py`, `tests/test_rag.py`
- 로컬 `.env`에는 로컬 backend 설정을 추가했다. 기존 자격증명은 보존하고 사용하지 않으며 Git에 포함하지 않았다.
- requirements.txt에는 requests>=2.32,<3 한 줄만 추가했다. 기존 환경의 requests 2.34.2를 재사용했고 추가 패키지 설치 및 lock 파일 재생성을 하지 않았다.
