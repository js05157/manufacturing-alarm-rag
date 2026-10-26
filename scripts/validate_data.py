"""Source/structure validation gate; not a claim of expert semantic review."""
import argparse
import hashlib
import re

import pymupdf

from config import ROOT, Settings, configure_console
from scripts.common import cell_text, compact, fingerprint, read_json, write_json


def verify(data, pdf):
    actual_hash = hashlib.sha256(pdf.read_bytes()).hexdigest()
    if data["source_sha256"] != actual_hash:
        raise ValueError("PDF hash differs from the extraction source")
    pymupdf.TOOLS.set_small_glyph_heights(True)
    accepted, rejected = [], []
    with pymupdf.open(pdf) as doc:
        words = {i+1: p.get_text("words") for i, p in enumerate(doc)}
        def evidence_text(evidence):
            if evidence["source_pdf"] != pdf.name or not 1 <= evidence["pdf_page"] <= len(doc):
                return ""
            return cell_text(words[evidence["pdf_page"]], evidence["bbox"]) or ""
        def has_text(text, evidence):
            original = compact(" ".join(evidence_text(e) for e in evidence))
            # Bullet separators may disappear between adjacent source cells.
            return compact(text) in original
        for record in data["alarms"] + data["symptoms"]:
            problems = []
            if not record.get("name") or not record.get("sources"):
                problems.append("missing name/source")
            if any(i.get("table") == record["record_id"] and i.get("stage") == "alarm" for i in data["issues"]):
                problems.append("unparsed alarm fields")
            if "codes" in record:
                if not record["description"]:
                    problems.append("missing description")
                for kind in ("description", "check_points", "actions", "references", "notes"):
                    for item in record[kind]:
                        if not has_text(item["text"], item["evidence"]):
                            problems.append(f"source mismatch: {item['id']}")
                        if "\ufffd" in item["text"] or re.search(r"[\ue000-\uf8ff]", item["text"]):
                            problems.append(f"invalid glyph: {item['id']}")
                for code, item in record["data_codes"].items():
                    match = re.fullmatch(r"(\d+)\s*\(H([0-9A-F]+)\)", item["value"])
                    if not match or not has_text(item["value"], [item["source"]]):
                        problems.append(f"source mismatch data code: {code}")
                    elif int(match[1]) != int(match[2], 16) and item.get("consistent") is not False:
                        problems.append(f"invalid decimal/hex data code: {code}")
            else:
                if not record["rows"]:
                    problems.append("empty symptom table")
                for row in record["rows"]:
                    if not all(has_text(row[k], [row[k+"_source"]]) for k in ("cause", "action") if row[k]):
                        problems.append(f"source mismatch: {row['id']}")
            if problems:
                rejected.append({"record_id": record["record_id"], "problems": problems})
            else:
                accepted.append(record["record_id"])
    return {"source_sha256": actual_hash, "dataset_fingerprint": fingerprint(data),
            "method": "PDF hash, table structure, source-coordinate text, decimal/hex consistency; no LLM judge",
            "accepted": accepted, "rejected": rejected, "extraction_issues": data["issues"]}


def load_verified(path=ROOT / "data/processed/alarms.json", report=ROOT / "data/processed/validation.json"):
    data, validation = read_json(path), read_json(report)
    if fingerprint(data) != validation["dataset_fingerprint"]:
        raise ValueError("검증 후 데이터가 변경되었습니다. validate_data를 다시 실행하세요.")
    if hashlib.sha256(Settings().pdf.read_bytes()).hexdigest() != validation["source_sha256"]:
        raise ValueError("원본 PDF가 변경되었습니다. 전체 파이프라인을 다시 실행하세요.")
    accepted = set(validation["accepted"])
    return data, [r for r in data["alarms"] if r["record_id"] in accepted], [r for r in data["symptoms"] if r["record_id"] in accepted]


def main():
    configure_console()
    p = argparse.ArgumentParser()
    p.add_argument("--input", default=str(ROOT / "data/processed/alarms.json"))
    p.add_argument("--pdf", type=__import__("pathlib").Path, default=Settings().pdf)
    args = p.parse_args()
    result = verify(read_json(args.input), args.pdf)
    write_json(ROOT / "data/processed/validation.json", result)
    print(f"Accepted {len(result['accepted'])}, quarantined {len(result['rejected'])}")
    for record in result["rejected"]:
        print(record)


if __name__ == "__main__":
    main()
