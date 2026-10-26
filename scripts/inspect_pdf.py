"""Local inspection helper; outputs remain ignored."""
import json
import sys
from pathlib import Path

import pymupdf

sys.stdout.reconfigure(encoding="utf-8")
doc = pymupdf.open("data/raw/E800매뉴얼_보수편.pdf")
Path("tmp/pdfs").mkdir(parents=True, exist_ok=True)
Path("tmp/full.txt").write_text("\n".join(f"=== PDF {i+1} ===\n" + p.get_text() for i, p in enumerate(doc)), encoding="utf-8")
print("pages", len(doc), "toc", doc.get_toc()[:30])
for n in (16, 17, 18, 19, 20, 24, 34, 35, 36, 37, 38, 42):
    p = doc[n-1]
    tables = p.find_tables()
    data = [{"bbox": t.bbox, "rows": t.extract(), "cells": t.cells} for t in tables.tables]
    Path(f"tmp/pdfs/page-{n}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    p.get_pixmap(matrix=pymupdf.Matrix(1, 1)).save(f"tmp/pdfs/page-{n}.png")
    print("\nPAGE", n, "tables", len(data))
    for t in data:
        print(json.dumps(t["rows"][:8], ensure_ascii=False))
    if n == 16:
        print("WORDS", p.get_text("words")[-50:])
        table = tables.tables[-1]
        for row in table.rows[:5]:
            print("CELLS", row.cells)
            for cell in row.cells:
                if cell:
                    words = [w[4] for w in p.get_text("words") if cell[0] <= (w[0]+w[2])/2 < cell[2] and cell[1] <= (w[1]+w[3])/2 < cell[3]]
                    print("CENTER", words)
