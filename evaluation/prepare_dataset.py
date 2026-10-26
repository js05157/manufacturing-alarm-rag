"""Freeze source-backed gold data locally after the extraction validation gate."""
from config import ROOT, configure_console
from evaluation.cases import CASES
from scripts.common import fingerprint, write_json
from scripts.validate_data import load_verified


def main():
    configure_console()
    data, alarms, symptoms = load_verified()
    cases = []
    for identifier, category, question, target in CASES:
        records = [a for a in alarms if target in a["codes"]] if target and not target.startswith("2.6.") else []
        symptom = next((s for s in symptoms if s["section"] == target), None)
        if target and not records and not symptom:
            raise ValueError(f"Gold target missing: {identifier}: {target}")
        facts = [{"id": i["id"], "text": i["text"], "sources": i["evidence"]}
                 for r in records for k in ("description", "check_points", "actions", "notes") for i in r[k]]
        # Open symptom questions have several valid rows. Store the complete
        # source section and require manual relevance review, not an invented code.
        case = {"id": identifier, "category": category, "question": question,
                "expected_code": target if records else None, "expected_section": target if symptom else None,
                "required_facts": facts, "symptom_gold": symptom["rows"] if symptom else [],
                "expected_record_ids": [r["record_id"] for r in records],
                "expect_abstention": category == "unknown", "requires_manual_review": bool(symptom) or identifier == "u05",
                "verification": "source_coordinates_and_authored_target_checked"}
        cases.append(case)
    output = {"schema_version": 1, "source_sha256": data["source_sha256"],
              "dataset_fingerprint": fingerprint(data), "case_spec_fingerprint": fingerprint(CASES),
              "review_note": "Targets checked against original PDF tables; automatic source-text verification is not expert diagnostic validation. Development set, no held-out split.",
              "questions": cases}
    write_json(ROOT / "evaluation/questions.json", output)
    print(f"Prepared {len(cases)} source-backed questions. Open symptom relevance remains manually reviewable.")


if __name__ == "__main__":
    main()
