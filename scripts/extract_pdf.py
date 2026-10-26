"""Extract the complete source plus auditable table cells (no LLM extraction)."""
import argparse
import hashlib
import logging

import pymupdf

from config import ROOT, Settings, configure_console
from scripts.common import cell_text, write_json


def extract(pdf_path, output):
    # The embedded Korean font reports a 2.8x-tall em box. Reduce to fontsize
    # before selecting centres; otherwise even centre-based selection crosses rows.
    pymupdf.TOOLS.set_small_glyph_heights(True)
    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF를 {pdf_path} 에 준비해 주세요. 가상 데이터를 생성하지 않습니다.")
    pages, errors = [], []
    with pymupdf.open(pdf_path) as doc:
        toc = doc.get_toc()
        if len(doc) != 64 or not any("2.6" in t[1] for t in toc) or "E800" not in str(toc):
            raise ValueError("지원하는 64페이지 FR-E800 보수편 PDF 구조와 다릅니다. 원문을 확인하세요.")
        for i, page in enumerate(doc):
            words = page.get_text("words")
            tables = []
            try:
                found = page.find_tables()
                for ti, table in enumerate(found.tables):
                    cells = [list(r.cells) for r in table.rows]
                    tables.append({"id": f"p{i+1}-t{ti}", "bbox": list(table.bbox), "cells": cells,
                                   "rows": [[cell_text(words, c) for c in row] for row in cells],
                                   "default_rows": table.extract()})
            except Exception as exc:
                errors.append({"pdf_page": i+1, "error": str(exc)})
                logging.exception("Table extraction failed on page %s", i+1)
            # Footer is excluded from body, but retained in raw text/words.
            lines = []
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    text = "".join(s["text"] for s in line["spans"]).strip()
                    lines.append({"text": text, "bbox": list(line["bbox"])})
            pages.append({"pdf_page": i+1, "printed_page": str(i) if 6 <= i+1 <= 60 else None,
                          "text": page.get_text(), "words": words, "lines": lines, "tables": tables})
        result = {"schema_version": 1, "source_pdf": pdf_path.name,
                  "source_sha256": hashlib.sha256(pdf_path.read_bytes()).hexdigest(),
                  "page_count": len(doc), "toc": toc, "pages": pages, "errors": errors}
    write_json(output, result)
    return result


def main():
    configure_console()
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", type=__import__("pathlib").Path, default=Settings().pdf)
    parser.add_argument("--output", type=__import__("pathlib").Path, default=ROOT / "data/processed/extracted.json")
    args = parser.parse_args()
    result = extract(args.pdf, args.output)
    print(f"{result['page_count']} pages, {sum(len(p['tables']) for p in result['pages'])} tables, {len(result['errors'])} failures")


if __name__ == "__main__":
    main()
