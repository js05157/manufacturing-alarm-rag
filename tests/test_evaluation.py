from evaluation.cases import CASES
from evaluation.evaluate import percentile, score_answer


def test_dataset_targets_and_percentile_definition():
    assert len(CASES) == 40
    assert len({c[0] for c in CASES}) == 40
    assert {k: sum(c[1] == k for c in CASES) for k in ("code", "symptom", "mixed", "unknown")} == {"code": 10, "symptom": 15, "mixed": 10, "unknown": 5}
    assert sum(c[1] == "symptom" and c[3] and not c[3].startswith("2.6") for c in CASES) == 10
    assert percentile([1, 2, 3, 4], .95) == 3.8499999999999996
    assert percentile([], .95) is None


def test_missing_facts_fail_and_uncertainty_is_reviewable():
    case = {"expect_abstention": False, "required_facts": [{"id": "fact", "text": "complete condition"}],
            "expected_code": "E.TEST", "expected_section": None, "expected_record_ids": ["r1"]}
    answer = {"validation": {"valid": True}, "evidence_ids": ["fact"], "text": "complete condition", "status": "evidence",
              "retrieval": {"records": [{"record_id": "r1", "codes": ["E.TEST"]}], "symptom_rows": []}}
    assert score_answer(case, answer)[0]
    answer["status"] = "unconfirmed"
    assert score_answer(case, answer)[0]  # Complete sources may reject a conjecture.
    answer["text"] = "condition"
    assert not score_answer(case, answer)[0]
    case["expect_abstention"] = True
    answer["status"] = "unconfirmed"
    assert score_answer(case, answer)[0]


def test_hit_at_one_is_separate_from_hit_at_three_and_evidence_only_accuracy():
    from types import SimpleNamespace
    from evaluation.evaluate import evaluate
    def question(identifier, target):
        return {"id":identifier,"category":"symptom","question":identifier,"expected_code":target,
                "expected_section":None,"required_facts":[],"expected_record_ids":[],
                "expect_abstention":False,"requires_manual_review":False}
    cases=[question("first","A"),question("second","B")]
    candidates={"first":["B","A"],"second":["B","A"]}
    def answer(q, **kwargs):
        code="A" if q=="first" else "B"
        return {"status":"evidence","text":"transport fixture", "elapsed_seconds":.1,"evidence_ids":[],
                "validation":{"valid":True},"retrieval":{"records":[{"record_id":"fixture","codes":[code]}],"symptom_rows":[]}}
    service=SimpleNamespace(vector=SimpleNamespace(encoder=SimpleNamespace(query=lambda _:None),code_candidates=lambda q:candidates[q]),answer=answer)
    progress=[]
    rows,metrics=evaluate({"questions":cases},service,"evidence_only",1,on_result=lambda rows:progress.append(len(rows)))
    assert metrics["hit_at_1"] == .5 and metrics["hit_at_3"] == 1.
    assert metrics["answer_accuracy"] is None and progress == [1,2]
    rows, metrics = evaluate({"questions": cases}, service, "llm", 1)
    assert metrics["answer_accuracy"] is None and metrics["answer_pending_review"] == 2
    review = {f"{r['id']}:0": {"approved": True, "answer_fingerprint": "stale"} for r in rows}
    assert evaluate({"questions": cases}, service, "llm", 1, review=review)[1]["answer_judged"] == 0
    review = {f"{r['id']}:0": {"approved": i == 0, "answer_fingerprint": r["answer_fingerprint"]} for i, r in enumerate(rows)}
    judged = evaluate({"questions": cases}, service, "llm", 1, review=review)[1]
    assert judged["answer_accuracy"] == .5 and judged["answer_pending_review"] == 0
