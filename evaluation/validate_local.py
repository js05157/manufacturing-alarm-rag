"""Opt-in real Qwen inference checks, separate from mocked pytest and old metrics."""
import hashlib
import json
import re
import socket
import statistics
import xml.etree.ElementTree as ET
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter

from config import ROOT, Settings, configure_console
from rag.local_llm import ContextBudgetError, LocalLLM, LocalLLMError
from rag.pipeline import RAGService
from scripts.common import fingerprint, read_json, write_json

CASES = [
    ("code", "E.OC1 알람의 내용과 체크 포인트 및 대처 방법을 알려줘.", "E.OC1"),
    ("mixed", "E.THT가 가감속 시간 때문일 수 있어?", "E.THT"),
    ("symptom", "모터 시동이 걸리지 않고 조작 패널도 표시되지 않아. 주회로 전원은 무엇을 확인해?", "2.6.1"),
    ("fan_noise", "냉각팬을 교환한 뒤 인버터에서 이상음이 나. 확인할 부분은?", "2.6.3"),
    ("unsupported", "E.OC1을 없애는 펌웨어 업데이트 파일의 다운로드 주소를 알려줘.", None),
    ("unknown", "E.OC999 알람의 해결 방법은?", None),
]


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def index_signature(vector):
    data = vector.collection.get(include=["embeddings", "metadatas", "documents"])
    rows = sorted([{ "id": identifier, "embedding": embedding.tolist(), "metadata": metadata, "document": document}
                   for identifier, embedding, metadata, document in zip(data["ids"], data["embeddings"], data["metadatas"], data["documents"])], key=lambda r: r["id"])
    return fingerprint(rows)


def write_report(results):
    """Publish aggregate measurements only; detailed manual answers stay local."""
    directory = ROOT / "evaluation/local_llm"
    regression_path = directory / "retrieval_regression/results.json"
    regression = read_json(regression_path) if regression_path.exists() else None
    retrieval_note = "- 이번 검색 회귀는 미실행이다. retrieval_regression 명령을 별도로 실행해야 한다."
    if regression:
        retrieval_note = f"- 기존 Hit@3: 90% (9/10). 이번 동일 40문항 검색 회귀: {regression['metrics']['hit_at_3']:.0%} ({regression['metrics']['hit_eligible']}개 대상), 코드 없는 자연어 {regression['metrics']['hit_excluded_no_code']}개 제외."
    ui_path = directory / "ui.json"
    ui = read_json(ui_path) if ui_path.exists() else None
    lines = ["# Qwen3 4B 로컬 통합 검증", "", f"실행: {results['run_at']}", "",
        "## 모델과 서버", "",
        f"- GGUF: `{results['server']['model_path']}` · {results['model_bytes']:,}바이트",
        f"- SHA-256: `{results['model_sha256']}`",
        f"- 다운로드 폴더의 같은 모델 파일 존재: {results['download_copy_exists']}",
        f"- llama.cpp `{results['server']['build']}`, 모델 alias `{results['model']}`",
        "- 시작 스크립트 기본 구성: 127.0.0.1:8080, CPU 최대 6개 물리 코어(Threads 옵션), GPU layers 0, parallel 1",
        f"- 컨텍스트 {results['context']}, 생성 상한 {results['max_tokens']}, temperature {results['temperature']}, seed 42",
        "- /no_think, enable_thinking=false, reasoning off 사용. 모델·E5는 로컬 파일만 사용하며 외부 LLM 호출 없음.", "",
        "## 실제 Qwen 추론", "",
        f"단독 한국어 생성: {results['standalone']['elapsed_seconds']:.3f}초, 입력 {results['standalone']['prompt_tokens']}토큰, 출력 {results['standalone']['completion_tokens']}토큰, 한국어 확인={results['standalone']['korean']}.", "",
        "| 사례 | 실제 LLM 호출 수 | 전체 응답 시간 | 입력 토큰 | 출력 토큰 | 상태 | 근거 검사 |",
        "|---|---:|---:|---|---|---|---|"]
    for row in results["cases"]:
        answer, llm = row["answer"], row["answer"]["local_llm"]
        lines.append(f"| {row['id']} | {llm['batch_count']} | {answer['elapsed_seconds']:.3f}초 | {llm['prompt_tokens']} | {llm['completion_tokens']} | {answer['status']} | {'통과' if row['passed'] else '실패'} |")
    lines += ["", f"실제 LLM을 호출한 RAG 사례의 평균 전체 응답 시간: **{results['mean_rag_seconds']:.3f}초**.",
        "서버는 이미 로드된 상태이며 prompt/KV 캐시를 사용한다. 답변 문자열 캐시는 사용하지 않는다. E5는 한 번 예열했다. 단독·RAG 수치는 단일 실행 사례의 측정값으로, 브라우저 렌더링과 모델 최초 로딩을 제외한다. 초기 실행이나 캐시 상태가 다른 요청은 더 오래 걸릴 수 있다.", "",
        "Qwen의 응답은 실제 llama.cpp API의 모델명과 토큰 사용량을 검증했다. 모의 응답으로 이 표를 계산하지 않았다. unknown 사례는 미등록 코드로 사전 중단되어 LLM을 호출하지 않았다.", "",
        "## 검색 성능과 답변 정확도 구분", "",
        retrieval_note,
        "- 기존 부족 전압 자연어 질의의 검색 실패는 남아 있다. 이번 통합에서 검색 지표를 개선했다고 주장하지 않는다.",
        "- 위 사례의 근거·출처·필수 목록 검사는 전체 40문항 LLM 답변 정답률을 뜻하지 않는다. **전체 40문항 로컬 LLM 정답률은 미측정**이다.",
        "- 기존 추출형 생성 계약을 유지한다. Qwen이 한국어 원문 근거를 선택해 생성하고 프로그램이 필수 목록을 보완한다. 자유로운 진단 문장의 의미적 정답을 보장하지 않는다.", "",
        "## 실패 처리와 회귀 검사", "",
        f"- 실제 로컬 토크나이저로 4096토큰 초과 요청 차단: {results['context_overflow_rejected']}",
        f"- 실제 미사용 loopback 포트의 연결 실패 처리: {results['connection_failure_handled']}",
        "- 여러 요청으로 나누는 원문 항목 단위 분할, HTTP 오류, 잘린 생성, 잘못된 JSON, 비어 있는 답변, 서버 모델 불일치, 외부 API로 자동 전환하지 않는 처리는 모의 테스트에서 검사한다.",
        "- Windows 시작 스크립트의 파일 누락 및 다른 프로세스의 포트 점유 오류도 검사한다. 실행 중인 프로세스를 종료하지 않는다."]
    junit = ROOT / "logs/local-tests.xml"
    if junit.exists():
        suites = ET.parse(junit).getroot().findall("testsuite")
        totals = {k: sum(int(s.get(k, 0)) for s in suites) for k in ("tests", "failures", "errors", "skipped")}
        lines.append(f"- 최근 전체 pytest JUnit 기록: {totals['tests']}개, 실패 {totals['failures']}, 오류 {totals['errors']}, 건너뜀 {totals['skipped']}.")
    if ui:
        lines.append(f"- 실제 Streamlit→로컬 Qwen 연결: 예외 없음={ui['no_exception']}, 오류 없음={ui['no_error']}, PDF 출처={ui['has_pdf_citation']}, 로컬 생성 시간 표시={ui['local_timing_displayed']}, 대화 기록 유지={ui['history_preserved']}.")
    lines += ["", "## 원본 보존", "",
        f"- 기존 Chroma 컬렉션 `{results['collection']}`, {results['chunk_count']}개 청크 재사용. 재색인 없음.",
        f"- 문서·메타데이터·임베딩 전체 지문 일치: {results['index_unchanged']}",
        f"- 컬렉션 지문: `{results['index_signature']}`"]
    for path, unchanged in results.get("original_artifacts_unchanged", {}).items():
        lines.append(f"- `{path}` SHA-256 보존: {unchanged}")
    lines += ["", "## 미완료·한계", "",
        "- 전체 40문항 실제 로컬 LLM 정답률과 반복 실행 p50/p95는 미측정이다.",
        "- 실제 사례는 모두 한 요청에 들어갔다. 복수 요청 분할은 모의 검증이며 실제 대규모 다중 알람 생성 성능으로 해석하지 않는다.",
        "- CPU 추론은 긴 프롬프트에서 지연이 크며 서버 prompt/KV 캐시 상태에 따라 시간이 달라진다.",
        "- 이 보고서에는 원문 대량 데이터·전체 답변을 포함하지 않는다. 상세 결과는 Git에서 제외된 smoke/results.json, ui.json, retrieval_regression/results.json에 보존한다."]
    lines += ["", "## 변경 파일", "",
        "- 설정·UI·의존성: `.env.example`, `.gitignore`, `config.py`, `app.py`, `requirements.txt`",
        "- 서버·전송·생성: `scripts/start_llm.ps1`, `rag/local_llm.py`, `rag/local_answer_generator.py`, `rag/pipeline.py`",
        "- 근거 순서·검증·오프라인 검색: `rag/answer_generator.py`, `rag/answer_validator.py`, `rag/embeddings.py`, `rag/vector_retriever.py`, `rag/router.py`",
        "- 검증·문서: `evaluation/evaluate.py`, `evaluation/validate_local.py`, `evaluation/local_llm/REPORT.md`, `evaluation/local_llm/retrieval_regression/REPORT.md`, `README.md`",
        "- 테스트: `tests/test_local_llm.py`, `tests/test_start_llm.py`, `tests/test_app.py`, `tests/test_rag.py`",
        "- 로컬 `.env`에는 로컬 backend 설정을 추가했다. 기존 자격증명은 보존하고 사용하지 않으며 Git에 포함하지 않았다.",
        "- requirements.txt에는 requests>=2.32,<3 한 줄만 추가했다. 기존 환경의 requests 2.34.2를 재사용했고 추가 패키지 설치 및 lock 파일 재생성을 하지 않았다."]
    if results["errors"]:
        lines += ["", "## 실행 오류", "", *[f"- {e['id']}: {e['error']}" for e in results["errors"]]]
    (directory / "REPORT.md").write_text("\n".join(lines)+"\n", encoding="utf-8")


def run(output):
    settings = replace(Settings(), llm_backend="local")
    client = LocalLLM(settings)
    results = {"run_at": datetime.now(timezone(timedelta(hours=9))).isoformat(),
               "model": settings.local_llm_model, "server": client.server,
               "model_bytes": settings.local_llm_model_path.stat().st_size,
               "model_sha256": file_hash(settings.local_llm_model_path),
               "download_copy_exists": (Path.home() / "Downloads" / settings.local_llm_model_path.name).exists(),
               "context": settings.local_llm_context, "max_tokens": settings.local_llm_max_tokens,
               "temperature": settings.local_llm_temperature, "reasoning": "off; /no_think; enable_thinking=false",
               "cases": [], "errors": []}
    output.mkdir(parents=True, exist_ok=True)
    def save():
        write_json(output / "results.json", results)
    standalone = client.complete([{"role": "system", "content": "한국어로 한 문장만 답하세요. /no_think"},
                                  {"role": "user", "content": "제조설비 매뉴얼을 확인하는 이유를 설명해 주세요."}], max_tokens=100)
    results["standalone"] = {**asdict(standalone), "korean": bool(re.search(r"[가-힣]", standalone.content))}
    print(json.dumps({"standalone_seconds": standalone.elapsed_seconds, "korean": results["standalone"]["korean"]}), flush=True)
    save()
    service = RAGService(settings)
    service.vector.encoder.query("인버터 알람 점검")  # Warm E5 once before per-query timing.
    results["collection"] = service.vector.manifest["collection"]
    results["chunk_count"] = service.vector.collection.count()
    before_index = index_signature(service.vector)
    for identifier, question, target in CASES:
        started = perf_counter()
        try:
            answer = service.answer(question)
            tokens = answer["local_llm"]
            target_present = True
            if target and target.startswith("2.6."):
                target_present = any(r["section"] == target for r in answer["retrieval"]["symptom_rows"])
            elif target:
                target_present = any(target in r["codes"] for r in answer["retrieval"]["records"])
            abstained = answer["status"] in ("insufficient", "unconfirmed")
            passed = answer["validation"]["valid"] and target_present
            if identifier in ("unsupported", "unknown"):
                passed = passed and abstained
            if identifier != "unknown":
                passed = passed and tokens["batch_count"] > 0
            passed = passed and all(p+c+settings.local_llm_margin <= tokens["context_limit"] for p, c in zip(tokens["prompt_tokens"], tokens["completion_tokens"]))
            row = {"id": identifier, "question": question, "passed": bool(passed), "target_present": target_present,
                   "korean": bool(re.search(r"[가-힣]", answer["text"])), "answer": answer}
            if identifier == "mixed":
                row["highlight_mentions_acceleration_time"] = any("가감속" in h["quote"] for h in answer["highlights"])
            results["cases"].append(row)
            print(json.dumps({"case": identifier, "passed": row["passed"], "seconds": answer["elapsed_seconds"],
                              "status": answer["status"], "batches": tokens["batch_count"], "prompt_tokens": tokens["prompt_tokens"]}), flush=True)
        except Exception as exc:
            results["errors"].append({"id": identifier, "error": type(exc).__name__+": "+str(exc), "seconds": perf_counter()-started})
            print(json.dumps({"case": identifier, "error": type(exc).__name__+": "+str(exc)}, ensure_ascii=True), flush=True)
        save()
    try:
        client.complete([{"role": "user", "content": "가"*10000}], max_tokens=100)
        results["context_overflow_rejected"] = False
    except ContextBudgetError:
        results["context_overflow_rejected"] = True
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        unused_port = probe.getsockname()[1]
    disconnected = LocalLLM(replace(settings, local_llm_url=f"http://127.0.0.1:{unused_port}/v1", local_llm_timeout=1))
    try:
        disconnected.complete([{"role": "user", "content": "연결 확인"}])
        results["connection_failure_handled"] = False
    except LocalLLMError as exc:
        results["connection_failure_handled"] = "연결할 수 없습니다" in str(exc)
    results["index_signature"] = before_index
    results["index_unchanged"] = before_index == index_signature(service.vector)
    baseline_path = ROOT / "tmp/local-integration-baseline.json"
    if baseline_path.exists():
        results["original_artifacts_unchanged"] = {p: file_hash(ROOT / p) == value for p, value in read_json(baseline_path).items()}
    generated = [r["answer"]["elapsed_seconds"] for r in results["cases"] if r["answer"]["local_llm"]["batch_count"]]
    results["mean_rag_seconds"] = statistics.mean(generated) if generated else None
    results["full_40_question_llm_accuracy"] = None
    save()
    write_report(results)
    print(json.dumps({"mean_rag_seconds": results["mean_rag_seconds"], "index_unchanged": results["index_unchanged"],
                      "context_overflow_rejected": results["context_overflow_rejected"], "connection_failure_handled": results["connection_failure_handled"]}), flush=True)
    return results


if __name__ == "__main__":
    configure_console()
    run(ROOT / "evaluation/local_llm/smoke")
