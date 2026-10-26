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
    answer["text"] = "condition"
    assert not score_answer(case, answer)[0]
    case["expect_abstention"] = True
    answer["status"] = "unconfirmed"
    assert score_answer(case, answer)[0]
