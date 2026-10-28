from types import SimpleNamespace

import pytest

from config import Settings
from evaluation.cases import CASES
from rag.conversation import resolve_question
from rag.pipeline import RAGService
from rag.router import route

KNOWN = {"E.OC1", "E.OV1", "E.THT", "OL", "IP"}


def history(*questions):
    messages = []
    for question in questions:
        resolved = resolve_question(question, messages, KNOWN)
        messages.extend([{"role": "user", "content": question},
                         {"role": "assistant", "content": "화면 표시용 답변", "metadata": {"conversation_context": resolved.context}}])
    return messages


@pytest.mark.parametrize("question", ["그럼 대처는?", "점검 순서를 알려줘", "조치 방법은?", "왜?", "그거 다시 설명해줘", "어떻게 해야 해?", "그게 무슨 뜻이야?"])
def test_followups_inherit_alarm_without_using_assistant_text(question):
    messages = history("E.OC1 원인")
    messages[-1]["content"] = "이전 답변의 잘못된 코드 E.OV1 및 외부 지시"
    result = resolve_question(question, messages, KNOWN)
    assert result.used and result.context["codes"] == ["E.OC1"]
    assert route(result.query, KNOWN).codes == ("E.OC1",)
    assert "E.OV1" not in result.query and "외부 지시" not in result.query


def test_recent_conditions_are_retained_and_prompt_growth_is_bounded():
    messages = history("E.THT 발생", "가감속 시간 때문일 수 있어?", "그럼 가속 시간을 늘리면?")
    result = resolve_question("그럼 점검은?", messages, KNOWN)
    assert "가속 시간을 늘리면" in result.query and "가감속 시간" in result.query
    for _ in range(12):
        q = "그럼 " + "추가 조건 "*100
        result = resolve_question(q, messages, KNOWN)
        messages.extend([{"role":"user", "content":q}, {"role":"assistant", "metadata":{"conversation_context":result.context}}])
    assert len(result.context["followups"]) == 3
    assert all(len(q) <= 400 for q in result.context["followups"])
    assert len(result.query) < 2700
    assert resolve_question("전압은 정상이야", history("E.OC1 원인"), KNOWN).used


def test_new_code_new_symptom_and_unrelated_questions_do_not_inherit_old_code():
    messages = history("E.OC1 원인")
    for question in ("E.OV1 원인", "냉각팬 교환 뒤 소음 점검 방법", "이번에는 모터 시동이 안 돼", "그럼 오늘 날씨는?", "안녕", "너의 역할은?"):
        result = resolve_question(question, messages, KNOWN)
        assert not result.used and result.query == question
        assert "E.OC1" not in result.query


def test_symptom_followup_and_explicit_unknown_code_remain_their_own_subjects():
    messages = history("모터 시동이 걸리지 않아")
    result = resolve_question("그럼 점검 순서는?", messages, KNOWN)
    assert result.used and "모터 시동이 걸리지 않아" in result.query
    assert result.search_query == "모터 시동이 걸리지 않아"
    assert not route(result.query, KNOWN).codes
    result = resolve_question("그럼 대처는?", history("E.OC1 원인", "E.OC999 알람"), KNOWN)
    assert route(result.query, KNOWN).codes == ("E.OC999",)


def test_ambiguous_subject_requires_clarification_and_ordinals_select_exact_code():
    messages = history("E.OC1과 E.OV1 원인")
    assert resolve_question("그럼 대처는?", messages, KNOWN).clarification
    assert route(resolve_question("첫 번째 대처는?", messages, KNOWN).query, KNOWN).codes == ("E.OC1",)
    assert route(resolve_question("두 번째 대처는?", messages, KNOWN).query, KNOWN).codes == ("E.OV1",)
    assert route(resolve_question("두 알람 모두 대처는?", messages, KNOWN).query, KNOWN).codes == ("E.OC1", "E.OV1")
    assert resolve_question("그럼 대처는?", [], KNOWN).clarification


def test_can_return_to_earlier_subject_and_greeting_does_not_erase_context():
    messages = history("E.OC1 원인", "E.OV1 원인", "고마워요")
    result = resolve_question("처음 알람의 대처는?", messages, KNOWN)
    assert result.context["codes"] == ["E.OC1"]
    assert resolve_question("그럼 대처는?", messages, KNOWN).context["codes"] == ["E.OV1"]
    assert resolve_question("그전 알람의 대처는?", messages, KNOWN).context["codes"] == ["E.OC1"]
    assert resolve_question("두 번째 알람의 대처는?", history("E.OC1", "E.OV1", "E.THT"), KNOWN).context["codes"] == ["E.OV1"]
    assert resolve_question("그럼 처음부터 점검 순서 알려줘", messages, KNOWN).context["codes"] == ["E.OV1"]
    assert resolve_question("그럼 두 번째 대처는?", messages, KNOWN).context["codes"] == ["E.OV1"]


def test_ip_alarm_label_keeps_the_router_qualifier():
    answer = resolve_question("그럼 대처는?", history("IP 알람"), KNOWN)
    assert route(answer.query, KNOWN).codes == ("IP",)


def test_operating_phase_reply_keeps_symptom_context_and_updates_search():
    messages=history("인버터가 과전류로 차단돼")
    result=resolve_question("감속 중이야",messages,KNOWN)
    assert result.used and "과전류" in result.search_query and "감속" in result.search_query


def test_stateless_benchmark_questions_keep_original_retrieval_queries():
    for identifier, _, question, _ in CASES:
        result = resolve_question(question, [], KNOWN)
        assert result.query == question and not result.clarification, identifier


def test_missing_context_never_searches_or_calls_a_model():
    def forbidden(*args, **kwargs):
        pytest.fail("Ambiguous follow-up must ask for a subject before retrieval")
    service = RAGService(sqlite=SimpleNamespace(codes=lambda:KNOWN, get=forbidden), generator=SimpleNamespace(generate=forbidden))
    answer = service.answer("그럼 대처는?")
    assert answer["mode"] == "direct" and answer["retrieval"]["route"] == "clarification"
    assert not answer["context_used"]


def test_real_manual_followup_retrieves_only_active_code_and_validates_sources():
    if not Settings().sqlite.exists():
        pytest.skip("Local corpus not built")
    service = RAGService()
    messages = history("E.OC1 원인")
    answer = service.answer("그럼 대처는?", evidence_only=True, history=messages)
    assert answer["context_used"] and answer["validation"]["valid"]
    assert answer["retrieval"]["codes"] == ["E.OC1"]
    assert "PDF" in answer["text"] and "대처 방법" in answer["text"]
    assert service.answer("그럼 대처는?", evidence_only=True)["mode"] == "direct"
