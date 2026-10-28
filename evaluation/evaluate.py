"""Separate retrieval, answer quality and latency, with durable progress records."""
import argparse
import csv
import importlib.metadata
import math
import platform
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config import ROOT, Settings, configure_console
from rag.pipeline import RAGService
from scripts.common import fingerprint, read_json, write_json


def percentile(values, p):
    if not values:
        return None
    values = sorted(values)
    position = (len(values)-1)*p
    lower, upper = math.floor(position), math.ceil(position)
    return values[lower]+(values[upper]-values[lower])*(position-lower)


def score_answer(case, answer):
    """Full-item exact evidence matching; ambiguous relevance goes to review."""
    if not answer["validation"]["valid"]:
        return False, ["programmatic_answer_validation_failed"]
    if case["expect_abstention"]:
        return answer["status"] in ("insufficient", "unconfirmed"), []
    missing = [f["id"] for f in case["required_facts"]
               if f["id"] not in answer["evidence_ids"] or f["text"] not in answer["text"]]
    codes = {c for r in answer["retrieval"]["records"] for c in r["codes"]}
    if case["expected_code"] and case["expected_code"] not in codes:
        missing.append("expected_alarm_code")
    if case["expected_record_ids"] and any(r["record_id"] not in case["expected_record_ids"] for r in answer["retrieval"]["records"]):
        missing.append("unexpected_alarm_record")
    if case["expected_section"]:
        if not any(r["section"] == case["expected_section"] for r in answer["retrieval"]["symptom_rows"]):
            missing.append("expected_symptom_section")
    # A source-complete answer may correctly decline to confirm a user
    # hypothesis. Its semantic appropriateness still requires separate review.
    return not missing and answer["status"] in ("evidence", "unconfirmed"), missing


def evaluate(dataset, service, mode, repeats, review=None, on_result=None):
    review = review or {}
    rows, hit_values, hit_first_values, latency = [], [], [], []
    # Weights and index warmed once. No query, embedding or answer result cache.
    service.vector.encoder.query("인버터 알람 점검")
    for case in dataset["questions"]:
        candidates = service.vector.code_candidates(case["question"]) if case["category"] == "symptom" and case["expected_code"] else []
        hit = case["expected_code"] in candidates if candidates else (False if case["category"] == "symptom" and case["expected_code"] else None)
        if hit is not None:
            hit_values.append(hit)
            hit_first_values.append(bool(candidates) and candidates[0] == case["expected_code"])
        for repeat in range(repeats):
            try:
                answer = service.answer(case["question"], evidence_only=mode == "evidence_only")
                seconds = answer["elapsed_seconds"]
                latency.append(seconds)
                diagnostic, missing = score_answer(case, answer)
                # All real LLM answers are pending until source-grounded review.
                correct = None
                manual = review.get(f"{case['id']}:{repeat}")
                if mode == "llm" and manual and manual.get("answer_fingerprint") == fingerprint(answer["text"]):
                    if manual.get("approved") is False:
                        correct = False
                    elif manual.get("approved") is True:
                        correct = diagnostic
                rows.append({"id": case["id"], "repeat": repeat, "category": case["category"], "question": case["question"],
                             "hit_at_3": hit, "hit_at_1": hit_first_values[-1] if hit is not None else None, "candidates": candidates, "answer_correct": correct,
                             "diagnostic_pass": diagnostic, "missing": missing, "elapsed_seconds": seconds,
                             "status": answer["status"], "error": None, "answer": answer["text"],
                             "answer_fingerprint": fingerprint(answer["text"]),
                             "needs_manual_review": correct is None if mode == "llm" else case["requires_manual_review"],
                             "retrieved_codes": sorted(codes_from_answer(answer)),
                             "retrieved_sections": sorted({r["section"] for r in answer["retrieval"]["symptom_rows"]}),
                             "model_highlights": answer.get("highlights", []), "local_llm": answer.get("local_llm", {})})
            except Exception as exc:
                rows.append({"id": case["id"], "repeat": repeat, "category": case["category"], "question": case["question"],
                             "hit_at_3": hit, "candidates": candidates, "answer_correct": False if mode == "llm" else None,
                             "diagnostic_pass": False, "missing": [], "elapsed_seconds": None, "status": "error",
                             "error": type(exc).__name__+": "+str(exc), "answer": "", "needs_manual_review": True,
                             "local_llm": {}})
            if on_result:
                on_result(rows)
    judged = [r["answer_correct"] for r in rows if r["answer_correct"] is not None]
    all_judged = len(judged) == len(rows)
    metrics = {"hit_at_3": sum(hit_values)/len(hit_values) if hit_values else None,
               "hit_at_1": sum(hit_first_values)/len(hit_first_values) if hit_first_values else None,
               "hit_eligible": len(hit_values), "hit_excluded_no_code": sum(c["category"] == "symptom" and not c["expected_code"] for c in dataset["questions"]),
               "answer_accuracy": sum(judged)/len(judged) if judged and all_judged else None,
               "answer_judged": len(judged), "answer_pending_review": len(rows)-len(judged) if mode == "llm" else 0,
               "latency_p50_seconds": statistics.median(latency) if latency else None,
               "latency_p95_seconds": percentile(latency, .95), "latency_successful": len(latency), "latency_failed": len(rows)-len(latency)}
    return rows, metrics


def codes_from_answer(answer):
    return {code for record in answer["retrieval"]["records"] for code in record["codes"]}


def save_results(output, dataset, rows, metrics, conditions):
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "results.json", {"conditions": conditions, "metrics": metrics, "rows": rows})
    fields = ["id", "repeat", "category", "hit_at_3", "answer_correct", "elapsed_seconds", "status", "needs_manual_review", "error"]
    with (output / "results.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    pct = lambda v: f"{v:.1%}" if v is not None else "미측정"
    sec = lambda v: f"{v:.4f}초" if v is not None else "미측정"
    mode_note = "원문 검색 확인 모드. 실제 LLM 호출을 하지 않았으므로 답변 정답률과 LLM 포함 응답 시간은 미측정." if conditions["mode"] == "evidence_only" else "LLM 모드. 모든 수동 검토가 끝나야 전체 답변 정답률을 확정한다."
    lines = ["# 성능 평가 보고서", "", f"실행: {conditions['run_at']}", "", mode_note, "",
             "| 핵심 지표 | 실제 결과 |", "|---|---|",
             f"| 검색 Hit@1 | {pct(metrics.get('hit_at_1'))} ({metrics['hit_eligible']}문항) |",
             f"| 검색 Hit@3 | {pct(metrics['hit_at_3'])} ({metrics['hit_eligible']}문항) |",
             f"| LLM 답변 정답률 | {pct(metrics['answer_accuracy'])} |",
             f"| 응답 시간 p50 / p95 | {sec(metrics['latency_p50_seconds'])} / {sec(metrics['latency_p95_seconds'])} |", "",
             f"응답 시간 범위: {conditions['mode']}. 성공 {metrics['latency_successful']}회, 실패 {metrics['latency_failed']}회. 실패는 분위수에 포함하지 않고 별도 기록한다.",
             f"코드 없는 자연어 질문 {metrics['hit_excluded_no_code']}개는 Hit@3에서 제외했다. 코드·복합·미등록 질문은 검색 지표 대상이 아니다.", "",
             "## 재현 조건", "", "```json", __import__("json").dumps(conditions, ensure_ascii=False, indent=2), "```", "",
             "## 판단 기준과 한계", "",
             "- Hit@3: 원문으로 확인한 정답 코드가 있는 자연어 질문만 사용. 전체 청크 검색 후 코드 중복을 제거해 상위 3개를 계산한다.",
             "- 답변: 필수 원문 항목 전체, 알람 코드, 페이지 출처, 출력 검증을 확인한다. 원문 항목을 잘라내거나 새로운 기술적 문장을 추가할 수 없는 생성 계약을 사용한다.",
             "- 증상 질문의 관련성 및 근거 부족 질문은 수동 검토 대상이다. 자동 검사는 진단의 의미적 정답을 보장하지 않는다.",
             "- evidence_only의 diagnostic_pass는 개발용 점검 로그이며 LLM 답변 정답률로 집계하지 않는다.",
             "- 작성된 소규모 개발용 평가 세트이며 독립적인 외부 시험 세트가 아니다. 이 문항의 결과만으로 일반적인 성능을 보장하지 않는다.",
             "- p95는 정렬한 값의 (N-1)*0.95 위치를 선형 보간한다. 모델 초기 로딩과 브라우저 렌더링은 제외한다.", "",
             "## 실패·검토 사례", ""]
    failures = [r for r in rows if r["hit_at_3"] is False or not r["diagnostic_pass"] or r["error"] or r["needs_manual_review"] or r.get("answer_correct") is False]
    if not failures:
        lines.append("이번 실행에서 자동 검사상 실패는 없었다. 의미적 정답 보장을 뜻하지 않는다.")
    for row in failures:
        lines.append(f"- {row['id']} (반복 {row['repeat']}): Hit@3={row['hit_at_3']}, 후보={row['candidates']}, 상태={row['status']}, 누락={row['missing']}, 검토대기={row['needs_manual_review']}, 오류={row['error']}, 검토={row.get('review_reason', '')}")
    lines += ["", "## 로컬 상세 기록", "", "results.json은 질문·응답·원문 항목 누락과 검토 지문을, results.csv는 실행별 결과를 저장한다. 원문 대량 재배포를 피하기 위해 두 파일은 Git에서 제외한다.",
              "LLM 수동 검토는 review.json에 질문ID:반복번호 키, approved, answer_fingerprint를 기록한 뒤 --rescore --review 경로로 실행한다. API를 다시 호출하지 않으며 응답이 변경되면 기존 검토는 적용되지 않는다."]
    (output / "REPORT.md").write_text("\n".join(lines)+"\n", encoding="utf-8")


def main():
    configure_console()
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["evidence_only", "llm"], default="evidence_only")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--review", type=Path)
    parser.add_argument("--dataset", type=Path, default=ROOT/"evaluation/questions.json")
    parser.add_argument("--output-dir", type=Path, help="Separate output directory; local mode defaults to evaluation/local_llm/evaluation")
    parser.add_argument("--rescore", action="store_true", help="Apply manual reviews to saved LLM responses without API calls")
    args = parser.parse_args()
    settings = Settings()
    output_dir = args.output_dir or (ROOT / "evaluation/local_llm/evaluation" if settings.llm_backend == "local" else ROOT / "evaluation")
    if args.repeats < 1:
        parser.error("repeats must be positive")
    if args.rescore:
        if not args.review:
            parser.error("--rescore requires --review")
        saved = read_json(output_dir / "results.json")
        if saved["conditions"]["mode"] != "llm":
            parser.error("Evidence-only results cannot become LLM accuracy measurements")
        review = read_json(args.review)
        for row in saved["rows"]:
            item = review.get(f"{row['id']}:{row['repeat']}")
            if item and item.get("answer_fingerprint") == row.get("answer_fingerprint") and isinstance(item.get("approved"), bool):
                row["answer_correct"] = row["diagnostic_pass"] and item["approved"]
                row["needs_manual_review"] = False
                row["review_reason"] = item.get("reason", "")
                row["reviewer"] = item.get("reviewer", "unspecified")
        judged = [r["answer_correct"] for r in saved["rows"] if r["answer_correct"] is not None]
        saved["metrics"]["answer_accuracy"] = sum(judged)/len(judged) if len(judged) == len(saved["rows"]) and judged else None
        saved["metrics"]["answer_judged"] = len(judged)
        saved["metrics"]["answer_pending_review"] = len(saved["rows"])-len(judged)
        save_results(output_dir, None, saved["rows"], saved["metrics"], saved["conditions"])
        print(saved["metrics"])
        return
    if args.mode == "llm" and settings.llm_backend == "openai" and not (settings.llm_model and settings.llm_api_key):
        parser.error("LLM_MODEL / LLM_API_KEY must be configured; no fallback model is used")
    dataset = read_json(args.dataset)
    source = read_json(ROOT / "data/processed/alarms.json")
    if fingerprint(source) != dataset["dataset_fingerprint"]:
        raise ValueError("Gold dataset is stale; revalidate and prepare it again")
    service = RAGService(settings)
    if service.sqlite.source_hash() != dataset["source_sha256"]:
        raise ValueError("Gold and database source hashes differ")
    conditions = {"run_at": datetime.now(timezone(timedelta(hours=9))).isoformat(), "mode": args.mode,
                  "backend": settings.llm_backend,
                  "model": (settings.local_llm_model if settings.llm_backend == "local" else settings.llm_model) if args.mode == "llm" else "not_called",
                  "embedding": service.vector.manifest["identity"], "source_sha256": dataset["source_sha256"],
                  "dataset_fingerprint": fingerprint(dataset), "platform": platform.platform(),
                  "processor": platform.processor(), "python": platform.python_version(), "question_count": len(dataset["questions"]),
                  "repeats": args.repeats, "top_k": settings.top_k, "max_distance": settings.max_distance,
                  "cache": "weights/index warm, no query/answer cache", "llm_max_tokens": settings.local_llm_max_tokens if settings.llm_backend == "local" else settings.llm_max_tokens,
                  "case_spec_fingerprint": dataset.get("case_spec_fingerprint"),
                  "retrieval_strategy": "e5_bm25_body_title_rrf_phase_v1", "local_output_contract": "evidence_ids_v2",
                  "packages": {n: importlib.metadata.version(n) for n in ("PyMuPDF", "chromadb", "sentence-transformers", "torch", "streamlit", "openai", "requests")}}
    def checkpoint(rows):
        write_json(output_dir/"checkpoint.json", {"conditions":conditions,"rows":rows})
        last=rows[-1]
        seconds=last.get("elapsed_seconds")
        timing=f"{seconds:.2f}s" if seconds is not None else "failed"
        print(f"[{len(rows)}/{len(dataset['questions'])*args.repeats}] {last['id']} {last['status']} {timing}", flush=True)
    rows, metrics = evaluate(dataset, service, args.mode, args.repeats, read_json(args.review) if args.review else None, on_result=checkpoint)
    save_results(output_dir, dataset, rows, metrics, conditions)
    print(metrics)


if __name__ == "__main__":
    main()
