import re
from dataclasses import dataclass

from scripts.parse_alarms import normalize_code


@dataclass(frozen=True)
class Route:
    kind: str
    codes: tuple[str, ...]


def route(question, known_codes):
    found = []
    patterns = [r"(?<![A-Za-z0-9.])E\.\s*[A-Za-z0-9]+(?:\.[A-Za-z0-9]+)*",
                r"(?<![A-Za-z0-9])Er(?:r\.|[0-9]+)(?![A-Za-z0-9])"]
    for pattern in patterns:
        found.extend((m.start(), normalize_code(m.group())) for m in re.finditer(pattern, question, re.I))
    for code in known_codes:
        if code.startswith("E.") or code.startswith("ER"):
            continue
        pattern = r"(?<![A-Za-z0-9/])"+re.escape(code)+r"(?![A-Za-z0-9/])"
        for match in re.finditer(pattern, question, re.I):
            if code == "IP" and not re.match(r"\s*(알람|코드|경보|발생|표시)", question[match.end():]):
                continue
            found.append((match.start(), code))
    for match in re.finditer(r"(?<![A-Za-z0-9.])([A-Z][A-Z0-9]{1,7})(?=\s*(?:알람|코드|경보))", question):
        found.append((match.start(), match[1]))
    codes = tuple(dict.fromkeys(code for _, code in sorted(found)))
    if not codes:
        return Route("symptom", ())
    mixed = bool(re.search(r"가감속|가속\s*시간|감속\s*시간|부하|전압|온도|발열|모터|시동|통신|원인일|때문|관련|가능|맞[아나]", question))
    return Route("mixed" if mixed else "code", codes)
