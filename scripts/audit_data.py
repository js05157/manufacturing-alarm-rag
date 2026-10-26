"""Print local extraction QA without publishing manual content."""
from config import configure_console
from scripts.common import read_json

configure_console()
d = read_json("data/processed/alarms.json")
print("ISSUES", d["issues"])
for a in d["alarms"]:
    print(a["record_id"], a["codes"], a["name"], a["classification"],
          [len(a[f]) for f in ("description", "check_points", "actions")],
          {k: v["value"] for k, v in a["data_codes"].items()})
e = read_json("data/processed/extracted.json")
for pn, tn in ((22, 3), (28, 4), (30, 2), (38, 0), (41, 1)):
    t = e["pages"][pn-1]["tables"][tn]
    print("SPECIAL", t["id"], t["rows"])
import pymupdf
pymupdf.TOOLS.set_small_glyph_heights(True)
with pymupdf.open("data/raw/E800매뉴얼_보수편.pdf") as doc:
    for b in doc[15].get_text("dict")["blocks"]:
        for l in b.get("lines", []):
            for s in l["spans"]:
                if s["text"].strip() in ("17", "(H11)", "E.OC2", "(H02)", "3"):
                    print("SPAN", s)
