# 설치와 실행

[README로 돌아가기](../README.md)

검증 환경은 Windows 10, Python 3.11, RAM 16GB, CPU 추론입니다. 기본 LLM은 Qwen3 4B Q4_K_M이며 GPU를 사용하지 않습니다.

## 1. Python 환경 준비

프로젝트 루트에서 실행합니다.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
Copy-Item .env.example .env
```

이미 `.env`가 있으면 복사하지 말고 기존 파일의 설정을 확인하세요. `requirements.lock.txt`는 검증 환경의 버전이며, 직접 의존성 범위는 [requirements.txt](../requirements.txt)에 있습니다.

## 2. PDF와 모델 준비

아래 파일은 공개 저장소에 포함되지 않습니다. 직접 준비한 파일의 경로를 `.env`에 지정합니다.

| 파일 | 기본 경로 |
|---|---|
| FR-E800 보수편 한국어 PDF, 64페이지 | `data/raw/E800매뉴얼_보수편.pdf` |
| Qwen3 4B Q4_K_M | `C:/AI/models/qwen3-4b/Qwen3-4B-Q4_K_M.gguf` |
| llama.cpp b11900 CPU 서버 | `C:/llama.cpp/llama-b11900-bin-win-cpu-x64/llama-server.exe` |

필수 로컬 설정 예시:

```dotenv
PDF_PATH=data/raw/E800매뉴얼_보수편.pdf
LLM_BACKEND=local
LLAMA_SERVER_PATH=C:/llama.cpp/llama-b11900-bin-win-cpu-x64/llama-server.exe
LOCAL_LLM_MODEL_PATH=C:/AI/models/qwen3-4b/Qwen3-4B-Q4_K_M.gguf
LOCAL_LLM_URL=http://127.0.0.1:8080/v1
LOCAL_LLM_PORT=8080
LOCAL_LLM_MODEL=qwen3-4b
LOCAL_LLM_CONTEXT=4096
LOCAL_LLM_MAX_TOKENS=512
LOCAL_LLM_TIMEOUT=180
LOCAL_LLM_TEMPERATURE=0.2
```

추가 설정은 [.env.example](../.env.example)에 있습니다. 로컬 모드는 `LLM_API_KEY`가 필요 없습니다. 파일 누락·모델 불일치는 오류로 처리하며, 다른 모델이나 외부 API로 자동 전환하지 않습니다.

## 3. 데이터 최초 구축

**기존 검증 DB와 인덱스가 있으면 이 단계를 생략합니다.** 최초 E5 모델 다운로드에는 네트워크가 필요하며, 서비스 실행 시에는 구축에 사용한 동일 revision의 로컬 캐시를 사용합니다.

```powershell
.\.venv\Scripts\python.exe -m scripts.extract_pdf
.\.venv\Scripts\python.exe -m scripts.parse_alarms
.\.venv\Scripts\python.exe -m scripts.validate_data
.\.venv\Scripts\python.exe -m scripts.build_sqlite
.\.venv\Scripts\python.exe -m scripts.build_chroma
```

| 결과물 | 기본 위치 |
|---|---|
| 텍스트·표·셀 좌표와 검증 기록 | `data/processed/` |
| 원문·코드·증상 SQLite | `storage/alarms.db` |
| Chroma 인덱스와 manifest | `storage/chroma/` |
| E5 모델 캐시 | `.cache/huggingface/` |

임베딩은 `intfloat/multilingual-e5-small`의 `query:` / `passage:` 규칙을 사용합니다. 구축 시 모델 revision·문서 해시를 manifest에 고정하며, 조회 시 불일치하면 검색을 중단합니다. 검증 실패 항목은 기록하고 적재하지 않습니다.

## 4. 서버와 화면 실행

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_llm.ps1
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
```

[채팅 화면](http://127.0.0.1:8501) · [LLM 상태](http://127.0.0.1:8080/health)

서버는 `127.0.0.1:8080`에만 바인딩합니다. 같은 모델의 정상 서버는 재사용하며, 파일 누락·다른 프로세스의 포트 점유는 명확한 오류로 표시합니다. 실행 중인 프로세스를 강제 종료하지 않습니다. 상태만 확인하려면 다음 명령을 사용합니다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_llm.ps1 -CheckOnly
```

시작 옵션은 `--ctx-size 4096 --gpu-layers 0 --parallel 1 --batch-size 512 --ubatch-size 128 --jinja --reasoning off --no-context-shift`입니다. 스레드는 물리 코어 수와 6 중 작은 값을 기본으로 사용하며 `-Threads`로 조정할 수 있습니다. 시작 로그는 Git에서 제외된 `logs/`에 남습니다.

질문 예시: `E.OC1의 원인과 대처 방법`, `E.THT가 가감속 시간 때문일 수 있어?`, `모터 시동이 걸리지 않아`.

## 답변 생성 방식

코드 질문은 SQLite 정확 검색, 코드 없는 기술 증상은 E5·Chroma 상위 3개 검색을 사용합니다. 인사·서비스 소개·범위 밖 질문은 먼저 안내합니다. 미등록 코드를 유사 코드로 대체하지 않습니다.

로컬 Qwen은 한국어 원문 근거의 ID와 전체 인용을 선택합니다. 프로그램이 인용을 원문과 대조하고 필수 점검·대처를 원래 순서로 보완하며 매뉴얼명과 실제/인쇄 페이지를 검증합니다. 자유로운 진단보다 원문 보존을 우선합니다.

서버의 실제 토크나이저로 `프롬프트 + 생성 상한 512 + 여유 96 ≤ 4096`을 확인합니다. 원문 항목 전체를 유지한 채 요청을 나누며, 단일 항목 자체가 한도를 넘으면 잘라내지 않고 오류로 처리합니다. `/no_think`와 `enable_thinking=false`를 적용합니다.

## 테스트와 평가

```powershell
# 모의 LLM/HTTP, 검색, 원문 검증, UI 회귀 검사
.\.venv\Scripts\python.exe -m pytest -q

# 평가용 질문·정답 원문 준비 (최초 1회, 로컬 PDF/DB 필요)
.\.venv\Scripts\python.exe -m evaluation.prepare_dataset

# 검색 평가 — LLM 호출 없음, 기존 결과와 별도 저장
.\.venv\Scripts\python.exe -m evaluation.evaluate --mode evidence_only --repeats 1 --output-dir evaluation/local_llm/retrieval_regression

# 실제 Qwen 추론·RAG·출처·연결 실패 검사
.\.venv\Scripts\python.exe -m evaluation.validate_local
```

원본 데이터가 없는 환경에서는 일부 원문 통합 검사가 건너뛰어집니다. 모의 테스트 통과, 검색 Hit@3, 실제 LLM 답변 정답률은 서로 다른 지표입니다. [초기 평가](../evaluation/REPORT.md), [로컬 통합 검증](../evaluation/local_llm/REPORT.md), [의도 분기 후 검색 회귀](../evaluation/local_llm/intent_regression/REPORT.md)를 구분해 확인하세요.

전체 40문항 로컬 LLM 생성 평가는 아직 미실행입니다. 필요하면 `evaluation.evaluate --mode llm --repeats 1 --output-dir evaluation/local_llm/full`로 실행하고, 질문과 원문을 대조한 수동 검토까지 완료한 뒤 정답률을 확정합니다.

## 데이터 해석 시 주의점

- `E.SAF`의 사양별 상세 레코드와 원문에 명시된 코드 묶음을 보존합니다. 점검과 대처 사이에 문서에 없는 1:1 연결을 만들지 않습니다.
- PDF 실제 페이지(1부터), 문서 내부 페이지, 원본 셀 좌표를 함께 보존합니다.
- 원문 `E.OA`의 데이터 코드 `212 (HDD)`는 십진수/16진수가 불일치합니다. 원문을 유지하고 `consistent=false`로 기록합니다.
- 특정 PDF 판본의 표 구조를 대상으로 합니다. 다른 판본·제조사·OCR 문서는 별도의 추출·검증이 필요합니다.
