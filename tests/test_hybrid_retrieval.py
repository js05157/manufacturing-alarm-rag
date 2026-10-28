from types import SimpleNamespace
import pytest

from config import Settings
from rag.lexical_ranker import BM25, terms
from rag.local_answer_generator import expand_selection
from rag.local_llm import LocalLLMError
from rag.pipeline import RAGService
from rag.router import route
from rag.vector_retriever import score_ranks, select_evidence, title_phases, phases


def hit(identifier, name, record, code=None, section=None):
    # Transport-only ranking fixture; never ingested into the manual corpus.
    return {"id":identifier, "text":f"{code} {name}" if code else name,
            "metadata":{"content_type":"alarm" if code else "symptom", "record_id":record,
                        "error_code":code,"section":section}}


def test_warning_code_is_not_matched_inside_a_longer_alarm_code():
    assert route("E.EHR Ethernet 이상", {"E.EHR","EHR"}).codes == ("E.EHR",)
    assert route("E.EHR과 EHR의 차이", {"E.EHR","EHR"}).codes == ("E.EHR","EHR")
    assert route("E.FN", {"FN"}).codes == ("E.FN",)


def test_korean_spacing_and_equal_scores_do_not_depend_on_identifier_order():
    assert set(terms("부족 전압")) & set(terms("부족전압"))
    bm=BM25(["부족 전압\n전원 저하", "모터 과열\n냉각 확인"])
    assert bm.scores("부족전압")[0] > bm.scores("부족전압")[1]
    assert score_ranks({"b":2.,"a":2.,"c":0.}) == {"a":1,"b":1}


def test_only_the_selected_alarm_family_is_expanded():
    hits=[hit("x","대상 알람","one","X"),hit("z","다른 알람","two","Z"),hit("y","대상 알람","one","X")]
    selected,reason=select_evidence(hits,"대상 알람",3)
    assert not reason and [h["id"] for h in selected]==["x","y"]


def test_same_name_different_records_requires_code_but_source_aliases_do_not():
    hits=[hit("a","같은 명칭","one","X"),hit("b","같은 명칭","two","Y")]
    assert select_evidence(hits,"같은 명칭")[1]
    hits[1]["metadata"]["record_id"]="one"
    assert not select_evidence(hits,"같은 명칭")[1]


def test_operating_phase_is_not_inferred_from_generic_stop_or_acceleration_names():
    assert title_phases("정속 중 과전류 차단")=={"정속"}
    assert title_phases("감속/정지 중 과전류 차단")=={"감속","정지"}
    assert not title_phases("스톨 방지에 의한 정지")
    assert not title_phases("가속도 이상")
    assert phases("정속 운전 중 회생 전압 상승으로 정지했다") == {"정속"}
    assert select_evidence([hit("a","가속 중 과전류 차단","one","X")],"과전류 차단")[1]


def test_second_symptom_requires_an_explicit_source_title_phrase():
    hits=[hit("a","조작 패널이 표시되지 않는다","r1",section="2.6.10"),
          hit("b","모터 시동이 걸리지 않는다","r2",section="2.6.1"),
          hit("c","모터가 역회전한다","r3",section="2.6.5")]
    selected,_=select_evidence(hits,"모터 시동이 걸리지 않고 조작 패널도 표시되지 않아")
    assert [h["id"] for h in selected]==["a","b"]


def test_shared_noise_word_does_not_mix_inverter_and_motor_symptoms():
    hits=[hit("a","인버터에서 이상음이 난다","r1",section="2.6.3"),
          hit("b","모터, 기계에서 이상음이 난다.","r2",section="2.6.2")]
    selected,_=select_evidence(hits,"냉각팬을 교환한 뒤 인버터에서 이상음이 나")
    assert [h["id"] for h in selected] == ["a"]


def test_explicit_source_areas_are_covered_without_changing_selected_rank_order():
    hits=[hit(str(i),"운전 중에 회전 속도가 변동한다","r",section="2.6.8") for i in range(4)]
    for i,h in enumerate(hits):
        h["text"] += "\n확인 부위: " + ("부하" if i==3 else "입력 신호") + "\n원인: 원문 행"
    selected,_=select_evidence(hits,"회전 속도가 변동한다. 부하와 입력 신호 점검",3)
    assert [h["id"] for h in selected] == ["0","1","3"]
    assert select_evidence(hits,"회전 속도가 변동한다",3)[0] == hits[:3]


def test_tripping_is_distinguished_from_stall_prevention_using_source_titles():
    hits=[hit("warning","스톨 방지(과전류)","w","OLC"),
          hit("steady","정속 중 과전류 차단","s","E.OC2"),
          hit("decel","감속/정지 중 과전류 차단","d","E.OC3")]
    assert select_evidence(hits,"인버터가 과전류로 차단돼")[1]
    selected,reason=select_evidence(hits,"인버터가 과전류로 차단돼 감속 중이야")
    assert not reason and [h["id"] for h in selected] == ["decel"]
    assert select_evidence(hits,"스톨 방지 과전류 차단을 방지한다")[0][0]["id"] == "warning"


@pytest.mark.parametrize("selection", [
    {"status":"evidence","evidence_ids":["missing"]},
    {"status":"evidence","evidence_ids":["x","x"]},
    {"status":"insufficient","evidence_ids":["x"]},
    {"status":"evidence","evidence_ids":[]},
    {"status":"evidence","evidence_ids":["x"],"text":"invented"},
])
def test_compact_llm_selection_rejects_unsupported_or_inconsistent_outputs(selection):
    with pytest.raises(LocalLLMError):
        expand_selection(selection,{"x":{"text":"전체 원문 조건"}})


def test_compact_selection_restores_full_original_conditions():
    plan=expand_selection({"status":"evidence","evidence_ids":["x"]},{"x":{"text":"조건을 생략하지 않는 전체 원문"}})
    assert plan["highlights"]==[{"evidence_id":"x","quote":"조건을 생략하지 않는 전체 원문"}]


def test_real_manual_explicit_code_does_not_include_warning_suffix():
    if not Settings().sqlite.exists(): pytest.skip("Local corpus not built")
    answer=RAGService().answer("E.EHR 통신 점검",evidence_only=True)
    assert answer["retrieval"]["codes"]==["E.EHR"]
    assert len(answer["retrieval"]["records"])==1
    assert answer["validation"]["valid"]
