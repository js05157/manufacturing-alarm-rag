"""FR-E800 table-aware parser. Unrecognized structures are quarantined."""
import argparse
import re

from config import ROOT, configure_console
from scripts.common import cell_text, clean, compact, fingerprint, items, read_json, write_json

CODE = re.compile(r"E\.\s*[A-Z0-9]+|Er[1-4]|Err\.|[A-Z][A-Z0-9]{1,4}")
FIELDS = {"내용": "description", "체크 포인트": "check_points", "대처": "actions",
          "참고 자료": "references", "参照資料": "references"}


def normalize_code(code):
    return re.sub(r"(?<=\.)\s+(?=[A-Za-z0-9])", "", clean(code)).upper()


def source(extracted, page, rect, table=None, row=None):
    return {"source_pdf": extracted["source_pdf"], "pdf_page": page["pdf_page"],
            "printed_page": page["printed_page"], "bbox": list(rect), "table_id": table, "row": row}


def heading_before(page, table):
    candidates = [l for l in page["lines"] if l["bbox"][3] <= table["bbox"][1]+5
                  and l["bbox"][1] > 30 and ("■" in l["text"] or "\uf06e" in l["text"])]
    if candidates:
        return clean(candidates[-1]["text"].lstrip("■ \uf06e"))
    return None


def parse(extracted):
    alarms, symptoms, issues = [], [], list(extracted["errors"])
    listing = {}
    category_names = {"에러 메시지", "경보", "경고장", "중고장", "기타 표시"}
    category_events = []
    for page in extracted["pages"][15:17]:
        for line in page["lines"]:
            label = compact(line["text"]).lstrip("◆■ \uf075")
            if label in category_names:
                category_events.append(((page["pdf_page"], int(line["bbox"][0] > 290), line["bbox"][1]), label))
        for table in page["tables"]:
            rows = table["rows"]
            if not rows or "조작 패널 표시" not in (rows[0][0] or ""):
                continue
            x, y = table["bbox"][:2]
            preceding = [(key, value) for key, value in category_events if key < (page["pdf_page"], int(x > 290), y)]
            category = max(preceding)[1] if preceding else None
            # The index has crowded rows and two missed horizontal rules.
            # Pair decimal+hex tokens first, then align their midpoint to panel tokens.
            name_x = next((c[0] for c in table["cells"][0][2:] if c), table["bbox"][2])
            anchors = []
            for w in page["words"]:
                cx, cy = (w[0]+w[2])/2, (w[1]+w[3])/2
                if x <= cx < name_x and y < cy < table["bbox"][3] and CODE.fullmatch(w[4]):
                    code = normalize_code(w[4])
                    if not any(c == code and abs(cy-ay) < 2 for c, ay in anchors):
                        anchors.append((code, cy))
            if not anchors:
                continue
            dc_rect = table["cells"][0][-2] if len(rows[0]) == 5 else None
            pairs = []
            if dc_rect:
                tokens = sorted([w for w in page["words"] if dc_rect[0] <= (w[0]+w[2])/2 < dc_rect[2]
                                 and y < (w[1]+w[3])/2 < table["bbox"][3]
                                 and re.fullmatch(r"\d+|\(H[0-9A-F]+\)", w[4])], key=lambda w: w[1])
                for first, second in zip(tokens, tokens[1:]):
                    if first[4].isdigit() and re.fullmatch(r"\(H[0-9A-F]+\)", second[4]):
                        rect = [min(first[0], second[0])-.01, min(first[1], second[1])-.01,
                                max(first[2], second[2])+.01, max(first[3], second[3])+.01]
                        pairs.append(((first[1]+first[3]+second[1]+second[3])/4, first[4]+" "+second[4], rect))
            for code, cy in anchors:
                near = min(pairs, key=lambda p: abs(p[0]-cy)) if pairs else None
                value = near[1] if near and abs(near[0]-cy) < 8 else None
                listing[code] = {"name": None, "classification": category, "data_code": value,
                                 "source": source(extracted, page, near[2] if value else table["bbox"], table["id"])}
            if any(c == "ER1" for c, _ in anchors) and any(c == "ER4" for c, _ in anchors):
                for n in (2, 3):
                    listing[f"ER{n}"] = {**listing["ER1"]}
    symptom_toc = [(title.split("\t", 1)[0], title.split("\t", 1)[-1], n)
                   for level, title, n in extracted["toc"] if level == 3 and title.startswith("2.6.")]
    symptom_index = -1
    active_symptom = None
    active_alarm = None
    for page in extracted["pages"][17:42]:
        for table in sorted(page["tables"], key=lambda t: t["bbox"][1]):
            rows = table["rows"]
            if not rows:
                continue
            header = compact(rows[0][0])
            if header == "조작 패널 표시":
                panel = rows[0][1] or ""
                # E.MB1~7 is an explicitly printed range; preserve common evidence.
                if re.search(r"E\.MB1\s*[~～]\s*7", panel):
                    codes = [f"E.MB{i}" for i in range(1, 8)]
                elif re.search(r"E\.16\s*[~～]\s*(?:E\.)?20", panel):
                    codes = [f"E.{i}" for i in range(16, 21)]
                elif "HP1" in panel and "HP2" in panel:
                    codes = ["HP1", "HP2"]
                else:
                    match = CODE.match(panel)
                    codes = [match.group()] if match else []
                if not codes:
                    issues.append({"stage": "alarm", "table": table["id"], "reason": "unrecognized_panel", "text": panel})
                    continue
                name = heading_before(page, table)
                record = {"record_id": table["id"], "codes": [normalize_code(c) for c in codes],
                          "display_codes": codes, "name": name,
                          "section": "2.5", "classification": None, "data_codes": {},
                          "description": [], "check_points": [], "actions": [], "references": [], "notes": [],
                          "sources": [source(extracted, page, table["bbox"], table["id"])],
                          "verification": "pending"}
                last_field = None
                for ri, row in enumerate(rows[1:], 1):
                    label = compact(row[0])
                    if label == "명칭":
                        continue
                    if not label and last_field is None and CODE.fullmatch(compact(row[1])):
                        extra = compact(row[1])
                        record["codes"].append(normalize_code(extra))
                        record["display_codes"].append(extra)
                        continue
                    field = FIELDS.get(label)
                    if field:
                        last_field = field
                    elif not label and last_field == "description":
                        field = "description"  # Explicit merged description, e.g. OLC stages.
                    elif any(s for s in row if s):
                        issues.append({"stage": "alarm", "table": table["id"], "row": ri, "reason": "unknown_field", "label": label})
                        continue
                    else:
                        continue
                    text = "\n".join(s for s in row[1:] if s)
                    rects = [c for c in table["cells"][ri][1:] if c]
                    for item in items(text):
                        record[field].append({"id": f"{table['id']}:{field}:{len(record[field])}", "text": item,
                                              "evidence": [source(extracted, page, c, table["id"], ri) for c in rects]})
                for code in record["codes"]:
                    entry = listing.get(code)
                    if entry:
                        record["name"] = record["name"] or entry["name"]
                        record["classification"] = entry["classification"]
                        if entry["data_code"]:
                            record["data_codes"][code] = {"value": entry["data_code"], "source": entry["source"]}
                            dc_match = re.fullmatch(r"(\d+)\s*\(H([0-9A-F]+)\)", entry["data_code"])
                            consistent = bool(dc_match and int(dc_match[1]) == int(dc_match[2], 16))
                            record["data_codes"][code]["consistent"] = consistent
                            if not consistent:
                                issues.append({"stage": "source", "code": code, "reason": "source_decimal_hex_conflict",
                                               "value": entry["data_code"], "source": entry["source"]})
                if not record["classification"] and record["codes"] == ["FN"]:
                    record["classification"] = "경고장"
                if not record["classification"] and record["codes"] == ["UV"]:
                    record["classification"] = "경보"
                if not record["classification"] and record["codes"] in (["RD"], ["WR"], ["E.0"]):
                    record["classification"] = "기타 표시"
                if not record["name"]:
                    # Er1..Er4 share the explicitly printed parameter-input heading.
                    entry = next((v for k, v in listing.items() if k in record["codes"]), {})
                    record["name"] = entry.get("name")
                alarms.append(record)
                active_alarm = record
            elif header == "확인 부위" and len(rows[0]) == 3:
                # Each new numbered subsection is a new table; p36/p37 continue 2.6.1.
                if page["pdf_page"] not in (36, 37) or active_symptom is None:
                    symptom_index += 1
                    if symptom_index >= len(symptom_toc):
                        issues.append({"stage": "symptom", "table": table["id"], "reason": "no_matching_heading"})
                        continue
                    sec, title, expected_page = symptom_toc[symptom_index]
                    if expected_page != page["pdf_page"]:
                        raise ValueError(f"Symptom table/TOC mismatch: {sec}, PDF {page['pdf_page']}")
                    active_symptom = {"record_id": sec, "section": sec, "name": title, "rows": [], "sources": [], "verification": "pending"}
                    symptoms.append(active_symptom)
                active_symptom["sources"].append(source(extracted, page, table["bbox"], table["id"]))
                area, cause, cause_rect = None, None, None
                for ri, row in enumerate(rows[1:], 1):
                    area = compact(row[0]) or area
                    if compact(row[1]):
                        cause = compact(row[1])
                        cause_rect = table["cells"][ri][1]
                    action = compact(row[2])
                    cause_source = source(extracted, page, cause_rect, table["id"], ri) if cause_rect else None
                    action_rect = table["cells"][ri][2]
                    action_source = source(extracted, page, action_rect, table["id"], ri) if action_rect else None
                    # Nulls arise from explicit vertically merged cells in this table.
                    if cause and not action:
                        # Source contains merged cause/action explanatory rows.
                        active_symptom["rows"].append({"id": f"{table['id']}:row:{ri}", "area": area,
                                                       "cause": cause, "action": None,
                                                       "cause_source": cause_source, "action_source": None,
                                                       "evidence": source(extracted, page, table["bbox"], table["id"], ri)})
                        continue
                    if not cause or not action:
                        issues.append({"stage": "symptom", "table": table["id"], "row": ri, "reason": "missing_cause_or_action"})
                        continue
                    active_symptom["rows"].append({"id": f"{table['id']}:row:{ri}", "area": area,
                                                   "cause": cause, "action": action,
                                                   "cause_source": cause_source, "action_source": action_source,
                                                   "evidence": source(extracted, page, table["bbox"], table["id"], ri)})
        # Out-of-table qualification text is retained in a separate page context.
        # This avoids assigning a numbered footnote to the wrong alarm across pages.
    # Preserve nearby qualifications and footnotes, including a footnote continued
    # at the top of the next page. No neighbouring alarm table text is copied.
    for record in alarms:
        origin = record["sources"][0]
        pn, table_y = origin["pdf_page"], origin["bbox"][1]
        for page in extracted["pages"][pn-1:pn+1]:
            headings = [l for l in page["lines"] if "■" in l["text"]]
            stops = [l for l in page["lines"] if "■" in l["text"] or "◆" in l["text"] or compact(l["text"]).startswith("2.6")]
            if page["pdf_page"] == pn:
                before = [l for l in headings if l["bbox"][1] < table_y]
                low = before[-1]["bbox"][3] if before else table_y
                following = [l for l in stops if l["bbox"][1] > table_y and not any(t["bbox"][1] <= l["bbox"][1] <= t["bbox"][3] for t in page["tables"])]
                high = following[0]["bbox"][1] if following else 785
            else:
                # Only follow a footnote when the source description refers to it.
                markers = {m for i in record["description"] for m in re.findall(r"\*\d+", i["text"])}
                if not markers:
                    continue
                low, high = 35, headings[0]["bbox"][1] if headings else 35
                prefix_text = " ".join(l["text"] for l in page["lines"] if low < l["bbox"][1] < high)
                if not markers.intersection(re.findall(r"\*\d+", prefix_text)):
                    continue
            for line in page["lines"]:
                rect = line["bbox"]
                cy = (rect[1]+rect[3])/2
                if not low < cy < high or rect[3] > 785:
                    continue
                if any(t["bbox"][1] <= cy <= t["bbox"][3] for t in page["tables"]):
                    continue
                text = compact(line["text"])
                if not text or "2.6" in text or text == record["name"]:
                    continue
                record["notes"].append({"id": f"{record['record_id']}:notes:{len(record['notes'])}", "text": text,
                                        "evidence": [source(extracted, page, rect)]})
    contexts = []
    for page in extracted["pages"][11:42]:
        outside = []
        for line in page["lines"]:
            rect = line["bbox"]
            if rect[1] < 35 or rect[3] > 785 or not line["text"]:
                continue
            centre = ((rect[0]+rect[2])/2, (rect[1]+rect[3])/2)
            if any(t["bbox"][0] <= centre[0] <= t["bbox"][2] and t["bbox"][1] <= centre[1] <= t["bbox"][3] for t in page["tables"]):
                continue
            outside.append(line["text"])
        if outside:
            contexts.append({"record_id": f"context-p{page['pdf_page']}", "section": "2",
                             "text": "\n".join(outside), "source": source(extracted, page, [0, 35, 595, 785])})
    present = {c for a in alarms for c in a["codes"]}
    for code in sorted(set(listing)-present):
        issues.append({"stage": "coverage", "code": code, "reason": "listing_without_detail"})
    result = {"schema_version": 1, "source_pdf": extracted["source_pdf"], "source_sha256": extracted["source_sha256"],
              "alarms": alarms, "symptoms": symptoms, "contexts": contexts, "issues": issues,
              "extraction_fingerprint": fingerprint(extracted)}
    return result


def main():
    configure_console()
    p = argparse.ArgumentParser()
    p.add_argument("--input", default=str(ROOT / "data/processed/extracted.json"))
    p.add_argument("--output", default=str(ROOT / "data/processed/alarms.json"))
    args = p.parse_args()
    result = parse(read_json(args.input))
    write_json(args.output, result)
    write_json(ROOT / "data/processed/extraction_issues.json", result["issues"])
    print(f"{len(result['alarms'])} alarm records, {len({c for a in result['alarms'] for c in a['codes']})} codes, {len(result['symptoms'])} symptoms, {len(result['issues'])} review items")


if __name__ == "__main__":
    main()
