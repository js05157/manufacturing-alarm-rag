"""Deterministic request parsing; absent conditions remain absent."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from scripts.parse_alarms import normalize_code

CODE_PATTERN = re.compile(r"(?<![A-Za-z0-9.])E\.\s*[A-Za-z0-9]+(?:\.[A-Za-z0-9]+)*", re.I)


def _date_range(text: str, today: date) -> tuple[str | None, str | None]:
    explicit = re.search(r"(20\d{2})[-./](\d{1,2})[-./](\d{1,2})", text)
    if explicit:
        try:
            value = date(*(int(part) for part in explicit.groups())).isoformat()
        except ValueError:
            return None, None
        return value, value
    if "다음 주" in text or "다음주" in text:
        start = today + timedelta(days=(7 - today.weekday()))
        return start.isoformat(), (start + timedelta(days=6)).isoformat()
    if "모레" in text:
        value = (today + timedelta(days=2)).isoformat()
        return value, value
    if "내일" in text:
        value = (today + timedelta(days=1)).isoformat()
        return value, value
    if "오늘" in text:
        value = today.isoformat()
        return value, value
    return None, None


def _location(text: str) -> str | None:
    labeled = re.search(r"(?:지역|장소)\s*[:：]\s*([^,.;!?\n]{2,50})", text)
    if labeled:
        return labeled.group(1).strip()
    match = re.search(
        r"([A-Za-z가-힣][A-Za-z가-힣0-9.-]{1,24}(?:시|군|구|도)?(?:\s*,\s*[A-Za-z가-힣][A-Za-z가-힣 .-]{1,30})?)에서",
        text,
    )
    if not match:
        return None
    value = match.group(1).strip()
    if value in {"조건", "같은 조건", "이전 조건", "아까 조건"}:
        return None
    return value


def _duration(text: str) -> int | None:
    hours = re.search(r"(\d+(?:\.\d+)?)\s*시간", text)
    minutes = re.search(r"(\d+)\s*분", text)
    if not hours and not minutes:
        return None
    return round(float(hours.group(1)) * 60) if hours else int(minutes.group(1))


def analyze_request(text: str, *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(ZoneInfo("Asia/Seoul"))
    compact = re.sub(r"\s+", " ", text).strip()
    codes = list(dict.fromkeys(normalize_code(match.group()) for match in CODE_PATTERN.finditer(text)))
    planning = bool(re.search(r"계획|일정|언제|날짜|예약|정비\s*(?:잡|하|예정)", text))
    manual = bool(codes or re.search(r"알람|원인|점검|대처|조치|증상|인버터|모터", text))
    greeting = bool(re.fullmatch(r"(?:안녕(?:하세요)?|하이|hello|hi)[.!?~ ]*", compact, re.I))
    usage = bool(re.search(r"사용법|무엇을 할 수|뭘 할 수|기능", text))
    if greeting:
        intent = "greeting"
    elif usage:
        intent = "usage"
    elif planning:
        intent = "maintenance_plan"
    elif manual:
        intent = "manual_search"
    else:
        intent = "out_of_scope"

    start_date, end_date = _date_range(text, now.date())
    period = "morning" if "오전" in text else "afternoon" if "오후" in text else None
    conditions = {
        "alarm_codes": codes,
        "location": _location(text),
        "start_date": start_date,
        "end_date": end_date,
        "preferred_period": period,
        "duration_minutes": _duration(text),
        "weekdays_only": bool("평일" in text),
        "exclude_holidays": bool(re.search(r"공휴일\s*(?:제외|말고|빼)", text)),
        "no_precipitation": bool(re.search(r"비\s*(?:없는|안\s*오는|오지\s*않)|강수\s*(?:없는|0)", text)),
    }
    missing = []
    if intent == "maintenance_plan":
        if not start_date:
            missing.append("date")
        if conditions["no_precipitation"] and not conditions["location"]:
            missing.append("location")
    return {
        "intent": intent,
        "conditions": conditions,
        "missing": missing,
        "reason": "규칙 기반으로 요청의 명시 조건만 추출했습니다.",
    }


def merge_memory(previous: dict[str, Any], current: dict[str, Any], text: str) -> tuple[dict[str, Any], bool]:
    if not previous or not re.search(r"같은|그대로|아까|이전|그럼|그러면", text):
        return current, False
    merged = dict(previous)
    for key, value in current.items():
        if value not in (None, [], "") and not (isinstance(value, bool) and value is False):
            merged[key] = value
    if re.search(r"비\s*(?:상관\s*없이|조건\s*(?:제외|빼)|와도\s*돼)", text):
        merged["no_precipitation"] = False
    if re.search(r"공휴일\s*(?:포함|상관\s*없이|제외하지)", text):
        merged["exclude_holidays"] = False
    return merged, True
