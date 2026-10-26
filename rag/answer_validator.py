from scripts.common import compact


def ordered_symptom_rows(retrieval):
    """Keep symptom-group relevance, then preserve printed procedure row order."""
    group_order = {section: i for i, section in enumerate(dict.fromkeys(r["section"] for r in retrieval.symptom_rows))}
    return sorted(retrieval.symptom_rows, key=lambda r: (group_order[r["section"]], r["evidence"]["pdf_page"], r["evidence"].get("row") or 0))


def evidence_units(retrieval):
    units = {}
    for record in retrieval.records:
        for kind in ("description", "check_points", "actions", "references", "notes"):
            for item in record[kind]:
                units[item["id"]] = {**item, "kind": kind, "record_id": record["record_id"], "name": record["name"], "codes": record["codes"]}
    retrieval_ranks = {r["id"]: i+1 for i, r in enumerate(retrieval.symptom_rows)}
    for row in ordered_symptom_rows(retrieval):
        text = f"원인: {row['cause']}"
        if row["action"]:
            text += f" / 대책: {row['action']}"
        units[row["id"]] = {"id": row["id"], "text": text, "kind": "symptom", "name": row["name"], "codes": [],
                              "evidence": [row["evidence"]], "record_id": row["section"], "retrieval_rank": retrieval_ranks[row["id"]]}
    return units


def validate_plan(plan, units):
    if not isinstance(plan, dict) or set(plan)-{"status", "highlights"}:
        return False, ["unexpected response fields"]
    if plan.get("status") not in ("evidence", "insufficient"):
        return False, ["invalid status"]
    highlights = plan.get("highlights")
    if not isinstance(highlights, list) or len(highlights) > 6:
        return False, ["invalid highlights"]
    if plan["status"] == "insufficient" and highlights:
        return False, ["insufficient response must not assert evidence"]
    for highlight in highlights:
        if not isinstance(highlight, dict) or set(highlight) != {"evidence_id", "quote"}:
            return False, ["invalid highlight structure"]
        if not isinstance(highlight["evidence_id"], str):
            return False, ["invalid evidence id type"]
        unit = units.get(highlight["evidence_id"])
        # Whole evidence items only: substring quotes could drop a negation or
        # operating-condition qualifier while still passing a substring check.
        if not unit or not isinstance(highlight["quote"], str) or compact(highlight["quote"]) != compact(unit["text"]):
            return False, ["unsupported or truncated evidence quote"]
    if plan["status"] == "evidence" and not highlights:
        return False, ["no evidence selected"]
    return True, []


def validate_answer(answer, retrieval):
    units = evidence_units(retrieval)
    included = set(answer["evidence_ids"])
    required = {k for k, v in units.items() if v["kind"] in ("description", "check_points", "actions", "notes", "symptom")}
    if answer["status"] == "insufficient":
        return {"valid": not included, "missing_ids": [], "unknown_ids": sorted(included), "reason": "abstention"}
    missing = required-included
    unknown = included-set(units)
    wrong_text = [i for i in included & set(units) if units[i]["text"] not in answer["text"]]
    # Symptom rendering uses separate cause/action lines rather than unit text.
    for row in retrieval.symptom_rows:
        if row["id"] in wrong_text and row["cause"] in answer["text"] and (not row["action"] or row["action"] in answer["text"]):
            wrong_text.remove(row["id"])
    sources = all(units[i]["evidence"] for i in included & set(units))
    uncited = []
    for i in included & set(units):
        e = units[i]["evidence"][0]
        label = f"{e['source_pdf']} · PDF {e['pdf_page']}쪽 · 문서 {e['printed_page']}쪽"
        if label not in answer["text"]:
            uncited.append(i)
    valid = not missing and not unknown and not wrong_text and not uncited and sources
    return {"valid": bool(valid), "missing_ids": sorted(missing), "unknown_ids": sorted(unknown), "wrong_text_ids": wrong_text, "uncited_ids": uncited}
