import json
from types import SimpleNamespace

import pytest

from config import Settings
from evaluation.cases import CASES
from rag.answer_generator import render
from rag.answer_validator import evidence_units, validate_answer
from rag.local_answer_generator import LocalAnswerGenerator
from rag.pipeline import RAGService, Retrieval
from rag.router import route


@pytest.mark.parametrize("question,kind", [
    ("안녕 넌 뭐하는 놈이야?", "capability"), ("넌 뭐하는 놈이야?", "capability"),
    ("너 누구야?", "capability"), ("자기소개 해줘", "capability"), ("사용법 알려줘", "capability"),
    ("안녕하세요", "greeting"), ("안녕!", "greeting"), ("고마워요", "greeting"),
    ("내일 날씨 알려줘", "out_of_scope"), ("오늘 주식 추천해줘", "out_of_scope"),
    ("파이썬 오류를 고쳐줘", "out_of_scope"), ("자동차 모터가 고장났어", "out_of_scope"),
    ("이거 왜이래?", "clarification"), ("인버터가 이상해", "clarification"), ("알람이 떠", "clarification"),
    ("모터가 꿈을 꿀 수 있어?", "clarification"), ("인버터에 대해", "clarification"),
    ("모터가 시동되지 않아", "symptom"), ("냉각팬 교환 뒤 소음이 나", "symptom"),
    ("모터가 안 돌아", "symptom"), ("인버터가 멈췄어", "symptom"),
    ("Ethernet 접속이 안 돼", "symptom"), ("가감속이 원활하지 않아", "symptom"),
])
def test_non_code_intents(question, kind):
    assert route(question, set()).kind == kind


@pytest.mark.parametrize("question", ["안녕, E.THT의 원인과 대처는?", "너 E.OC1 알람 설명해줘"])
def test_explicit_code_takes_priority_over_greeting(question):
    decision = route(question, {"E.THT", "E.OC1"})
    assert decision.kind in ("code", "mixed") and decision.codes


def test_existing_benchmark_symptoms_still_reach_retrieval():
    for identifier, category, question, target in CASES:
        if category == "symptom":
            assert route(question, set()).kind == "symptom", identifier


@pytest.mark.parametrize("question", ["안녕 넌 뭐하는 놈이야?", "안녕", "오늘 날씨는?", "인버터가 이상해"])
def test_guidance_never_searches_or_calls_any_llm(question):
    def forbidden(*args, **kwargs):
        pytest.fail("Guidance must not retrieve documents or call a model")
    sqlite = SimpleNamespace(codes=lambda: set(), get=forbidden, symptom=forbidden)
    generator = SimpleNamespace(generate=forbidden)
    service = RAGService(sqlite=sqlite, vector=object(), generator=generator)
    answer = service.answer(question)
    assert answer["mode"] == "direct" and answer["status"] == "guidance"
    assert "vector" not in service.__dict__
    assert not answer["evidence_ids"] and not answer["retrieval"]["hits"]
    assert "대책:" not in answer["text"] and "PDF" not in answer["text"]


def unsupported_fixture():
    # In-memory transport fixture, never stored in the actual manual corpus.
    origin = {"source_pdf": "transport-fixture.pdf", "pdf_page": 7, "printed_page": "6", "row": 1}
    row = {"id": "fixture:row:1", "section": "2.6.1", "name": "테스트 증상", "area": "시험",
           "cause": "무관한 원인", "action": "무관한 조작 지침", "evidence": origin}
    return Retrieval("연관성을 확인할 수 없는 질문", "symptom", symptom_rows=[row])


def test_insufficient_symptom_evidence_does_not_emit_retrieved_procedures():
    retrieval = unsupported_fixture()
    answer = render(retrieval, evidence_units(retrieval), {"status": "insufficient", "highlights": []}, "local")
    assert answer["status"] == "insufficient" and not answer["evidence_ids"]
    assert "무관한 조작 지침" not in answer["text"] and "PDF" not in answer["text"]
    assert validate_answer(answer, retrieval)["valid"]


def test_local_model_abstention_reaches_final_answer_without_procedures():
    client = SimpleNamespace(context_limit=4096, count_tokens=lambda _: 100,
        complete=lambda *args, **kwargs: SimpleNamespace(content=json.dumps({"status": "insufficient", "evidence_ids": []}),
                                                         prompt_tokens=100, completion_tokens=10, context_limit=4096, elapsed_seconds=.01))
    answer = LocalAnswerGenerator(Settings(), client).generate(unsupported_fixture())
    assert answer["status"] == "insufficient" and answer["validation"]["valid"]
    assert "무관한 조작 지침" not in answer["text"]
