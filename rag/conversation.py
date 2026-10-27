"""Resolve follow-up subjects from user turns, never from generated diagnoses."""
import re
from dataclasses import dataclass, field

from rag.router import route

FOLLOWUP = re.compile(
    r"^(?:그럼|그러면|그거|그건|그것|그게|이거|이건|그에대해|그알람|그코드|이알람|해당|같은알람|아까|방금|이전|그전|앞서|앞에서|"
    r"첫번째|두번째|첫째|둘째|처음알람|처음질문|직전|다시|이어서|두알람|두코드|둘다)|"
    r"^(?:부하|온도|전압|전류|가속시간|감속시간|가감속시간)(?:은|는|이|가)|"
    r"왜그|관련(?:있|된)|때문|가능성|늘리면|줄이면"
)
TOPIC_CHANGE = re.compile(r"다른질문|새로운질문|새질문|주제(?:를)?바|별개|이번에는|이번엔")
BARE_FOLLOWUP = re.compile(
    r"(?:왜|어떻게|설명|자세히|더자세히|계속|다음|순서|원인|주의사항|"
    r"(?:대처|점검|조치|대책|확인)(?:방법|절차|순서)?|온도|전압|전류|설정값|가감속시간)"
    r"(?:는|은|을|를|이|가)?(?:좀)?(?:해줘|알려줘|설명해줘|알려주세요|해야해|하면돼|해야하나요|요)?[.!?~]*$"
)


@dataclass
class ConversationQuestion:
    query: str
    context: dict = field(default_factory=dict)
    used: bool = False
    clarification: str = ""
    search_query: str = ""


def _followup(text):
    compact = re.sub(r"\s+", "", text)
    return not TOPIC_CHANGE.search(compact) and bool(FOLLOWUP.search(compact) or BARE_FOLLOWUP.fullmatch(compact))


def _context(question, codes=()):
    return {"codes": list(codes), "topic": question[:600], "followups": []}


def _subjects(history, known_codes):
    subjects = []
    for message in history or []:
        if message.get("role") == "user":
            question = message.get("content", "")
            decision = route(question, known_codes)
            # A failed/unfinished explicit question still changes the subject.
            if decision.codes or (decision.kind == "symptom" and not _followup(question)):
                subjects.append(_context(question, decision.codes))
        elif message.get("role") == "assistant":
            saved = message.get("metadata", {}).get("conversation_context")
            if isinstance(saved, dict) and isinstance(saved.get("topic"), str):
                subjects.append({"codes": list(saved.get("codes", [])), "topic": saved["topic"][:600],
                                 "followups": list(saved.get("followups", []))[-3:]})
    # Keep the latest state of consecutive turns on the same subject.
    result = []
    for subject in subjects:
        key = tuple(subject["codes"]) or subject["topic"]
        previous = (tuple(result[-1]["codes"]) or result[-1]["topic"]) if result else None
        if key == previous:
            result[-1] = subject
        else:
            result.append(subject)
    return result


def resolve_question(question, history, known_codes):
    decision = route(question, known_codes)
    if decision.codes:
        return ConversationQuestion(question, _context(question, decision.codes))
    if decision.kind in ("greeting", "capability"):
        return ConversationQuestion(question)
    compact = re.sub(r"\s+", "", question)
    # Explicitly unrelated requests must never inherit an inverter alarm.
    if decision.kind == "out_of_scope" and re.search(
        r"날씨|주식|주가|투자|레시피|요리|영화|축구|파이썬|python|윈도우|windows|자동차|로봇|cr800", compact, re.I
    ):
        return ConversationQuestion(question)
    if not _followup(question):
        return ConversationQuestion(question, _context(question) if decision.kind == "symptom" else {})
    subjects = _subjects(history, known_codes)
    if not subjects:
        if decision.kind == "symptom" and not re.match(r"그럼|그러면|그거|아까|이전|해당|그알람", compact):
            return ConversationQuestion(question, _context(question))
        return ConversationQuestion(question, clarification="어떤 알람이나 증상에 대한 후속 질문인지 알려 주세요. 예: E.OC1의 대처 방법.")
    subject = subjects[-1]
    if re.search(r"처음(?:알람|질문|물어본|에물어본)|(?:첫번째|첫째)(?:알람|코드|질문)", compact) and len(subject["codes"]) <= 1:
        subject = subjects[0]
    elif re.search(r"(?:두번째|둘째)(?:알람|코드|질문)", compact) and len(subject["codes"]) <= 1 and len(subjects) > 1:
        subject = subjects[1]
    elif re.search(r"(?:그전|직전|이전)(?:알람|코드|질문)", compact) and len(subjects) > 1:
        subject = subjects[-2]
    codes = list(subject["codes"])
    if len(codes) > 1:
        if re.search(r"첫번째|첫째", compact):
            codes = codes[:1]
        elif re.search(r"두번째|둘째", compact):
            codes = codes[1:2]
        elif not re.search(r"모두|둘다|각각|두알람|각알람|비교|차이", compact):
            return ConversationQuestion(question, clarification=f"어느 알람에 대한 질문인가요? {', '.join(codes)} 중 코드를 지정해 주세요.")
    # Do not reintroduce other codes from an earlier multi-code question.
    previous = [subject["topic"], *subject["followups"]]
    previous = [text for text in previous if set(route(text, known_codes).codes) <= set(codes)]
    previous = [text[:400] for text in previous][-4:]
    label = ", ".join(f"{code} 알람" for code in codes) if codes else subject["topic"]
    query = f"대화 대상: {label}\n"
    if previous:
        query += "이전 사용자 질문(진단 근거 아님): "+" / ".join(previous)+"\n"
    query += "현재 질문: "+question
    context = {"codes": codes, "topic": subject["topic"] if len(codes) == len(subject["codes"]) else label,
               "followups": [*subject["followups"], question[:400]][-3:]}
    return ConversationQuestion(query, context, used=True, search_query=subject["topic"] if not codes else "")
