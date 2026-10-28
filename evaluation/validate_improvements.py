"""Opt-in real local inference checks; isolated chat DB and repeat timings."""
import argparse
import statistics
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from config import ROOT, Settings, configure_console
from evaluation.evaluate import percentile
from rag.chat_store import ChatStore
from rag.pipeline import RAGService
from scripts.common import read_json, write_json


def measured_answer(service, question, history=None):
    answer = service.answer(question, history=history)
    llm = answer.get("local_llm", {})
    return {"question": question, "answer": answer,
            "actual_calls": llm.get("batch_count", 0),
            "token_budget_valid": all(n + service.settings.local_llm_max_tokens + service.settings.local_llm_margin
                                      <= llm["context_limit"] for n in llm.get("prompt_tokens", []))}


def conversation(service, output):
    # The original voltage question is intentionally ambiguous between UV and
    # E.UVT. Its frozen strict gold is not changed to score clarification.
    voltage = next(c["question"] for c in read_json(ROOT / "evaluation/questions.json")["questions"] if c["id"] == "n07")
    cases = [
        ("code_start", "A", "E.THT의 원인과 대처 방법은?", False, "E.THT", False),
        ("code_followup", "A", "그럼 가감속 시간이 짧아서 그럴 수 있어?", True, "E.THT", False),
        ("new_code", "A", "E.OC1의 원인과 대처 방법은?", False, "E.OC1", False),
        ("empty_room", "B", "그럼 대처는?", False, None, True),
        ("earlier_code", "A", "처음 알람의 대처는?", True, "E.THT", False),
        ("phase_question", "C", "인버터가 과전류로 차단돼", False, None, True),
        ("phase_reply", "C", "감속 중이야", True, "E.OC3", False),
        ("voltage_question", "D", voltage, False, None, True),
        ("voltage_code", "D", "E.UVT 알람이야", False, "E.UVT", False),
        ("symptom_start", "E", "냉각팬을 교환한 뒤 인버터에서 이상음이 나. 확인할 부분은?", False, "2.6.3", False),
        ("symptom_followup", "E", "그럼 점검 순서는?", True, "2.6.3", False),
        ("unrelated", "E", "안녕", False, None, True),
    ]
    rows, room_ids, previous_hits = [], {}, {}
    with TemporaryDirectory(prefix="alarm-rag-evaluation-") as directory:
        path = Path(directory) / "chats.db"
        for identifier, room, question, context_used, target, direct in cases:
            store = ChatStore(path)  # Reopen the DB for every turn.
            room_ids.setdefault(room, None)
            if room_ids[room] is None:
                room_ids[room] = store.create_room()
            row = {"id": identifier, "room": room}
            try:
                row.update(measured_answer(service, question, store.messages(room_ids[room])))
                answer = row["answer"]
                codes = {c for r in answer["retrieval"]["records"] for c in r["codes"]}
                sections = {r["section"] for r in answer["retrieval"]["symptom_rows"]}
                checks = {"sources": answer["validation"]["valid"],
                          "context": answer["context_used"] == context_used,
                          "target": target is None or target in codes | sections,
                          "real_inference_or_direct": row["actual_calls"] == 0 if direct else row["actual_calls"] > 0,
                          "token_budget": row["token_budget_valid"]}
                hits = [h["id"] for h in answer["retrieval"]["hits"]]
                if identifier == "symptom_followup":
                    checks["symptom_ranking"] = hits == previous_hits[room]
                previous_hits[room] = hits
                row["checks"] = checks
                row["passed"] = all(checks.values())
                store.append(room_ids[room], "user", question)
                store.append(room_ids[room], "assistant", answer["text"],
                             {"conversation_context": answer["conversation_context"]})
            except Exception as exc:
                row.update(passed=False, error=type(exc).__name__ + ": " + str(exc))
            rows.append(row)
            write_json(output / "conversation.json", {"rows": rows})
            print(identifier, row["passed"], row.get("actual_calls"), row.get("checks", row.get("error")), flush=True)
    return rows


def latency(service, output, repeats):
    questions = [("code", "E.THT의 원인과 대처 방법은?"),
                 ("alarm_symptom", "가속 중 과전류로 차단됐어. 점검 및 대처 방법은?"),
                 ("table_symptom", "냉각팬을 교환한 뒤 인버터에서 이상음이 나. 확인할 부분은?")]
    rows = []
    for repeat in range(repeats):
        for identifier, question in questions:
            row = {"id": identifier, "repeat": repeat}
            try:
                row.update(measured_answer(service, question))
                row["passed"] = row["actual_calls"] > 0 and row["answer"]["validation"]["valid"] and row["token_budget_valid"]
            except Exception as exc:
                row.update(passed=False, error=type(exc).__name__ + ": " + str(exc))
            rows.append(row)
            write_json(output / "latency.json", {"rows": rows})
            print(identifier, repeat, row["passed"], row.get("answer", {}).get("elapsed_seconds"), flush=True)
    groups = {}
    for identifier in [q[0] for q in questions] + ["all"]:
        selected = [r for r in rows if identifier == "all" or r["id"] == identifier]
        seconds = [r["answer"]["elapsed_seconds"] for r in selected if r["passed"]]
        groups[identifier] = {"successful": len(seconds), "failed": len(selected)-len(seconds),
                              "mean": statistics.mean(seconds) if seconds else None,
                              "p50": statistics.median(seconds) if seconds else None,
                              "p95": percentile(seconds, .95)}
    return {"rows": rows, "summary": groups}


def main():
    configure_console()
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("conversation", "latency"), required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "evaluation/local_llm/improved/validation")
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("repeats must be positive")
    settings = replace(Settings(), llm_backend="local")
    service = RAGService(settings)
    service.vector.encoder.query("인버터 알람 점검")
    conditions = {"run_at": datetime.now(timezone.utc).isoformat(), "mode": args.mode,
                  "backend": "local", "model": settings.local_llm_model,
                  "cache": "model/E5 already loaded; server prompt/KV cache enabled; no answer cache",
                  "excluded": "model first load, browser rendering; no concurrent inference benchmark"}
    result = conversation(service, args.output_dir) if args.mode == "conversation" else latency(service, args.output_dir, args.repeats)
    write_json(args.output_dir / (args.mode + ".json"), {"conditions": conditions, "result": result})


if __name__ == "__main__":
    main()
