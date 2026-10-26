from dataclasses import replace
from types import SimpleNamespace

import pytest

from config import ROOT, Settings
from rag.answer_generator import AnswerGenerator
from rag.answer_validator import evidence_units, validate_answer, validate_plan
from rag.pipeline import RAGService, Retrieval
from rag.router import route
from rag.sqlite_retriever import SQLiteRetriever
from rag.vector_retriever import unique_code_ranking


@pytest.mark.parametrize("question,expected", [
    ("e.oc1 알람", ("E.OC1",)), ("E.OC10의 원인", ("E.OC10",)),
    ("E.OC1과 E.OV1", ("E.OC1", "E.OV1")), ("Er1이 떠요", ("ER1",)),
    ("Err. 표시", ("ERR.",)), ("FN 경보", ("FN",)), ("OLC가 발생", ("OLC",)),
    ("E. 5 코드", ("E.5",)), ("E.OC1.2 알람", ("E.OC1.2",)),
    ("IP 주소를 확인해줘", ()), ("EtherNet/IP 통신이 안돼", ()),
    ("AE.OC1 또는 EOC1", ()), ("E.OC1A", ("E.OC1A",))])
def test_router_boundaries(question, expected):
    assert route(question, {"E.OC1", "FN", "OLC", "IP", "ER1", "ERR."}).codes == expected


def test_deduplicate_code_candidates():
    hits = [{"metadata": {"error_code": c}} for c in ("A", "A", None, "B", "A", "C")]
    assert unique_code_ranking(hits) == ["A", "B", "C"]


@pytest.fixture
def local_service():
    if not Settings().sqlite.exists():
        pytest.skip("Local corpus not built")
    return RAGService()


def test_exact_route_does_not_open_vector(local_service):
    answer = local_service.answer("E.OC1 알람 원인과 해결 방법", evidence_only=True)
    assert "vector" not in local_service.__dict__
    assert answer["validation"]["valid"]
    assert "PDF 23쪽" in answer["text"]
    assert len(answer["retrieval"]["records"][0]["check_points"]) == 10
    assert "E.OV1" not in answer["text"]


def test_unknown_code_abstains_without_vector_or_llm(local_service):
    result = local_service.answer("E.OC999 알람", evidence_only=False)
    assert result["status"] == "insufficient"
    assert result["evidence_ids"] == []
    assert "vector" not in local_service.__dict__


def test_variants_and_no_invented_actions(local_service):
    saf = local_service.answer("E.SAF", evidence_only=True)
    assert len(saf["retrieval"]["records"]) == 2
    er1 = local_service.answer("Er1", evidence_only=True)
    assert "대처 방법" not in er1["text"]


def test_llm_plan_rejects_fabrication_and_partial_quote(local_service):
    retrieval = local_service.retrieve("E.THT가 가감속 시간 때문일 수 있어?")
    units = evidence_units(retrieval)
    key, unit = next(iter(units.items()))
    plan = {"status": "evidence", "highlights": [{"evidence_id": key, "quote": unit["text"]}]}
    assert validate_plan(plan, units)[0]
    plan["highlights"][0]["quote"] = unit["text"][:10]
    assert not validate_plan(plan, units)[0]
    plan["highlights"][0]["quote"] = "무조건 리셋하세요"
    assert not validate_plan(plan, units)[0]


def test_llm_adapter_and_complete_rendering(local_service):
    import json
    retrieval = local_service.retrieve("E.OV1 원인")
    key, unit = next(iter(evidence_units(retrieval).items()))
    payload = {"status": "evidence", "highlights": [{"evidence_id": key, "quote": unit["text"]}]}
    calls = []
    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)), finish_reason="stop")])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    settings = replace(Settings(), llm_model="test-model", llm_api_key="test-placeholder")
    answer = AnswerGenerator(settings, client).generate(retrieval)
    assert answer["validation"]["valid"]
    assert calls[0]["model"] == "test-model"
    # Deliberately remove a mandatory procedure after rendering.
    victim = retrieval.records[0]["actions"][0]
    answer["text"] = answer["text"].replace(victim["text"], "")
    assert not validate_answer(answer, retrieval)["valid"]


def test_no_silent_model_substitution(local_service):
    retrieval = local_service.retrieve("E.OC1")
    with pytest.raises(ValueError, match="LLM_MODEL"):
        AnswerGenerator(replace(Settings(), llm_model="", llm_api_key="")).generate(retrieval)


def test_e5_prefixes_normalization_and_no_truncation():
    import numpy as np
    from rag.embeddings import E5Encoder
    calls = []
    def encode(texts, **kwargs):
        calls.append((texts, kwargs))
        return np.array([[1.0, 0.0] for _ in texts])
    tokenizer = SimpleNamespace(encode=lambda text, **kwargs: [1, 2, 3])
    model = SimpleNamespace(tokenizer=tokenizer, encode=encode)
    encoder = E5Encoder("test-encoder")
    encoder.__dict__["model"] = model
    assert encoder.passages(["문서"]) == [[1.0, 0.0]]
    assert encoder.query("질문") == [1.0, 0.0]
    assert calls[0][0] == ["passage: 문서"] and calls[1][0] == ["query: 질문"]
    assert all(kwargs["normalize_embeddings"] for _, kwargs in calls)
    tokenizer.encode = lambda *args, **kwargs: list(range(600))
    with pytest.raises(ValueError, match="silent truncation"):
        encoder.passages(["긴 문서"])
    with pytest.raises(ValueError, match="512"):
        encoder.query("긴 질문")


def test_source_and_model_mismatches_fail_before_search(local_service, tmp_path):
    from rag.vector_retriever import VectorRetriever
    from scripts.common import write_json
    write_json(tmp_path / "manifest.json", {"identity": {"model": "other", "revision": "a"*40}})
    with pytest.raises(ValueError, match="임베딩 모델"):
        VectorRetriever(tmp_path, "requested")
    service = RAGService(sqlite=local_service.sqlite, vector=SimpleNamespace(manifest={"source_sha256": "different"}))
    with pytest.raises(ValueError, match="원본 PDF"):
        service.vector


def test_chroma_corpus_and_symptom_evidence(local_service):
    manifest = Settings().chroma / "manifest.json"
    if not manifest.exists():
        pytest.skip("Local vector index not built")
    result = local_service.answer("인버터에 연결된 모터가 시동되지 않아", evidence_only=True)
    assert result["retrieval"]["route"] == "symptom"
    assert result["retrieval"]["hits"]
    assert result["validation"]["valid"]
