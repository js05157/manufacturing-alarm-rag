"""Freeze source-backed gold data locally after the extraction validation gate."""
import argparse
from pathlib import Path
from config import ROOT, configure_console
from evaluation.cases import CASES
from scripts.common import fingerprint, write_json
from scripts.validate_data import load_verified


def prepare(specification=CASES, review_note=None):
    data, alarms, symptoms = load_verified()
    cases = []
    for identifier, category, question, target in specification:
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
              "dataset_fingerprint": fingerprint(data), "case_spec_fingerprint": fingerprint(specification),
              "review_note": review_note or "Targets checked against original PDF tables; automatic source-text verification is not expert diagnostic validation. Development set, no held-out split.",
              "questions": cases}
    return output


def main():
    configure_console()
    parser=argparse.ArgumentParser()
    parser.add_argument("--additional", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT/"evaluation/questions.json")
    args=parser.parse_args()
    if args.additional:
        if args.output.resolve() == (ROOT/"evaluation/questions.json").resolve():
            parser.error("추가 문항은 기존 questions.json과 다른 출력 경로가 필요합니다.")
        from evaluation.additional_cases import CASES as additional
        output=prepare(additional, "Additional authored cases fixed before tuning; not an external expert benchmark.")
    else:
        output=prepare()
    write_json(args.output, output)
    print(f"Prepared {len(output['questions'])} source-backed questions. Open symptom relevance remains manually reviewable.")


if __name__ == "__main__":
    main()
