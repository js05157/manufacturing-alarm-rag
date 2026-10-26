"""Render source pages for local QA; never publish these artifacts."""
import argparse
from pathlib import Path
import pymupdf
from config import Settings, configure_console


def main():
    configure_console()
    parser = argparse.ArgumentParser()
    parser.add_argument("pages", nargs="*", type=int, default=list(range(18, 43)))
    args = parser.parse_args()
    output = Path("tmp/pdfs")
    output.mkdir(parents=True, exist_ok=True)
    with pymupdf.open(Settings().pdf) as doc:
        for n in args.pages:
            doc[n-1].get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5)).save(str(output / f"review-{n}.png"))
    print("Rendered", args.pages)


if __name__ == "__main__":
    main()
