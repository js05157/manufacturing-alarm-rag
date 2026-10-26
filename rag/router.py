import re
from dataclasses import dataclass

from scripts.parse_alarms import normalize_code


DIRECT_REPLIES = {
    "greeting": "안녕하세요. 저는 FR-E800 인버터의 알람과 증상 확인을 돕는 도우미입니다. 알람 코드나 설비에서 발생한 증상을 알려 주세요.",
    "capability": "저는 미쓰비시전기 FR-E800 인버터의 알람 코드와 증상을 제조사 보수 매뉴얼에서 찾아, 내용·체크 포인트·대처 방법과 페이지 출처를 안내하는 도우미입니다. 예를 들어 ‘E.THT의 원인과 대처’ 또는 ‘모터 시동이 걸리지 않아요’라고 질문해 주세요.",
    "clarification": "표시된 알람 코드나 구체적인 설비 증상을 알려 주세요. 예: E.OC1, 모터 시동 불가, 냉각팬 교환 후 이상음. 현재 질문만으로는 관련 점검 절차를 판단하기 어렵습니다.",
    "out_of_scope": "이 서비스는 FR-E800 인버터의 알람·증상 확인을 지원합니다. 알람 코드나 설비 증상을 알려 주시면 매뉴얼 근거와 출처를 안내하겠습니다.",
}

EQUIPMENT = re.compile(r"인버터|설비|모터|전동기|fr[\s-]?e800|e800", re.I)
SYMPTOM = re.compile(
    r"시동|기동|구동|회전|가감속|가속|감속|토크|주파수|전류|전압|과부하|발열|과열|서멀|서미스터|"
    r"냉각팬|이상음|소음|진동|배선|단자|절연|결상|지락|누전|접지|회생|브레이크|"
    r"파라미터|운전모드|입력신호|제어회로|조작패널|캐리어|이더넷|ethernet|modbus|cc-link|plg|pid|pwm|pr\.\d", re.I)


def non_code_intent(question):
    text = re.sub(r"\s+", "", question).casefold()
    if re.search(r"자기소개|누구(?:야|세요|니)|(?:너|넌|당신|이서비스|이사이트|이앱).{0,30}(?:뭐하는|무슨일|어떤일|뭘할|뭐할|무엇을할|해줄수|도와줄|역할|기능)|사용법|어떻게사용", text):
        return "capability"
    if re.fullmatch(r"(?:안녕(?:하세요|하십니까)?|하이|반가워요?|hello|hi|hey|감사합니다|고마워요?|수고했어)[.!?~]*", text):
        return "greeting"
    if re.search(r"날씨|주식|주가|비트코인|투자|레시피|요리|축구|영화|운세", text):
        return "out_of_scope"
    if re.search(r"파이썬|python|윈도우|windows|노트북|스마트폰|자동차|차량|로봇|cr800", text) and not re.search(r"인버터|fr[\s-]?e800|e800", text):
        return "out_of_scope"
    if re.fullmatch(r"(?:(?:인버터|설비|모터)(?:가|이|에)?(?:좀)?)?(?:이상해요?|안돼요?|문제가있어|고장났어|왜이래|도와줘)[.!?~]*", text):
        return "clarification"
    if SYMPTOM.search(text):
        return "symptom"
    if EQUIPMENT.search(text):
        if re.search(r"안[가-힣]{0,8}(?:돼|되|켜|돌|해)|않|불가|멈|정지|뜨거|뜨겁|작동하지|동작하지", text):
            return "symptom"
        return "clarification"
    if re.search(r"고장|문제|알람|경보|에러|오류|이거왜|왜이런", text):
        return "clarification"
    return "out_of_scope"


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
        return Route(non_code_intent(question), ())
    mixed = bool(re.search(r"가감속|가속\s*시간|감속\s*시간|부하|전압|온도|발열|모터|시동|통신|원인일|때문|관련|가능|맞[아나]", question))
    return Route("mixed" if mixed else "code", codes)
