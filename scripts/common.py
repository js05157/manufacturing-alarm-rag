import hashlib
import json
import re
import unicodedata
from pathlib import Path


def clean(text):
    # Preserve numbers, code punctuation and source spelling. No OCR guessing.
    return unicodedata.normalize("NFC", text or "").replace("\u00a0", " ").strip()


def compact(text):
    return re.sub(r"\s+", " ", clean(text))


def fingerprint(value):
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def items(text):
    text = clean(text)
    if not text or re.fullmatch(r"[\s\-─―—]+", text):
        return []
    # A visual line wrap is not an item boundary; bullets are.
    return [compact(s) for s in re.split(r"(?:^|\n)\s*•\s*", text) if compact(s)]


def cell_text(words, rect):
    """Select word centres, avoiding oversized Korean font bounding boxes."""
    if rect is None:
        return None
    selected = [w for w in words if rect[0] <= (w[0]+w[2])/2 < rect[2]
                and rect[1] <= (w[1]+w[3])/2 < rect[3]]
    lines = {}
    for w in selected:
        lines.setdefault((w[5], w[6]), []).append(w)
    ordered = sorted(lines.values(), key=lambda ws: (round(min(w[1] for w in ws), 1), min(w[0] for w in ws)))
    return clean("\n".join(" ".join(w[4] for w in sorted(ws, key=lambda w: w[0])) for ws in ordered))
