import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
import requests

from config import Settings
from rag.local_answer_generator import LocalAnswerGenerator, make_messages
from rag.local_llm import Completion, ContextBudgetError, LocalLLM, LocalLLMError
from rag.pipeline import RAGService, Retrieval


class FakeResponse:
    def __init__(self, data, status=200):
        self.data, self.status_code = data, status

    def json(self):
        if isinstance(self.data, Exception):
            raise self.data
        return self.data


class FakeSession:
    def __init__(self, settings):
        self.settings = settings
        self.trust_env = True
        self.calls = []
        self.failures = {}
        self.prompt_length = 20
        self.completion = {"model": settings.local_llm_model, "choices": [{"finish_reason": "stop", "message": {"content": "한국어 응답"}}],
                           "usage": {"prompt_tokens": 20, "completion_tokens": 10}}

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        path = url.removeprefix("http://127.0.0.1:8080")
        if path in self.failures:
            failure = self.failures[path]
            if isinstance(failure, Exception):
                raise failure
            return failure
        data = {
            "/health": {"status": "ok"},
            "/props": {"model_path": str(self.settings.local_llm_model_path), "default_generation_settings": {"n_ctx": 4096}, "total_slots": 1},
            "/v1/models": {"data": [{"id": self.settings.local_llm_model}]},
            "/apply-template": {"prompt": "formatted prompt with actual chat markers"},
            "/tokenize": {"tokens": [1]*self.prompt_length},
            "/v1/chat/completions": self.completion,
        }
        return FakeResponse(data[path])


def client_fixture():
    settings = replace(Settings(), local_llm_url="http://127.0.0.1:8080/v1", llm_api_key="must-not-be-sent")
    session = FakeSession(settings)
    return LocalLLM(settings, session), session


@pytest.mark.parametrize("url", ["https://api.openai.com/v1", "http://example.com:8080/v1", "http://0.0.0.0:8080/v1",
                                  "http://127.0.0.1/v1", "http://secret@127.0.0.1:8080/v1", "http://127.0.0.1:8080/v1?key=secret"])
def test_remote_or_ambiguous_endpoints_are_rejected(url):
    with pytest.raises(ValueError, match="외부 LLM"):
        LocalLLM(replace(Settings(), local_llm_url=url))


def test_requests_payload_budget_no_keys_proxies_or_redirects():
    client, session = client_fixture()
    result = client.complete([{"role": "system", "content": "한국어 /no_think"}])
    assert result.content == "한국어 응답" and result.prompt_tokens == 20
    assert session.trust_env is False
    assert all(call[2]["allow_redirects"] is False for call in session.calls)
    assert all(call[2]["timeout"][0] == 3 for call in session.calls)
    assert "must-not-be-sent" not in repr(session.calls)
    assert all("headers" not in call[2] for call in session.calls)
    payload = session.calls[-1][2]["json"]
    assert payload["chat_template_kwargs"] == {"enable_thinking": False}
    assert payload["reasoning_effort"] == "none"
    assert payload["max_tokens"] == 512
    assert "must-not-be-sent" not in repr(client.settings)


@pytest.mark.parametrize("failure,expected", [
    (requests.ConnectionError("private details"), "start_llm.ps1"),
    (requests.Timeout("private details"), "응답 시간이 초과"),
    (FakeResponse({"secret": "private details"}, 400), "요청을 거부"),
    (FakeResponse({}, 503), "로딩 중"),
    (FakeResponse({}, 302), "HTTP 302"),
    (FakeResponse(ValueError("private details")), "올바른 JSON"),
    (FakeResponse([]), "JSON 객체"),
])
def test_transport_errors_remain_visible_without_raw_payloads(failure, expected):
    client, session = client_fixture()
    session.failures["/health"] = failure
    with pytest.raises(LocalLLMError, match=expected) as error:
        client.complete([])
    assert "private details" not in str(error.value)
    assert len(session.calls) == 1


def test_context_overflow_is_rejected_before_generation():
    client, session = client_fixture()
    session.prompt_length = 3600
    with pytest.raises(ContextBudgetError):
        client.complete([])
    assert not any(url.endswith("/chat/completions") for _, url, _ in session.calls)


def test_multiple_slots_are_rejected_before_using_shared_context():
    client, session = client_fixture()
    session.failures["/props"] = FakeResponse({"total_slots": 2})
    with pytest.raises(LocalLLMError, match="parallel 1"):
        client.complete([])


@pytest.mark.parametrize("mutation,expected", [
    (lambda x: x.update(choices=[]), "choices"),
    (lambda x: x["choices"][0].update(finish_reason="length"), "잘렸거나"),
    (lambda x: x["choices"][0]["message"].update(content=""), "비어 있거나"),
    (lambda x: x["choices"][0]["message"].update(content="<think>private thought</think>답변"), "추론 태그"),
    (lambda x: x.update(usage={}), "토큰 사용량"),
    (lambda x: x.update(model="other-model"), "모델명"),
    (lambda x: x.update(usage={"prompt_tokens": 4000, "completion_tokens": 200}), "컨텍스트 예산"),
])
def test_completion_format_model_and_token_validation(mutation, expected):
    client, session = client_fixture()
    mutation(session.completion)
    with pytest.raises(LocalLLMError, match=expected):
        client.complete([])


def test_empty_thinking_wrapper_does_not_remove_answer():
    client, session = client_fixture()
    session.completion["choices"][0]["message"]["content"] = "<think>\n\n</think>\n실제 한국어 답변"
    assert client.complete([]).content == "실제 한국어 답변"


def source_fixture():
    # Synthetic in-memory transport fixture, never loaded into the real corpus.
    origin = {"source_pdf": "transport-fixture.pdf", "pdf_page": 7, "printed_page": "6"}
    return Retrieval("점검 질문", "code", records=[{
        "record_id": "fixture", "codes": ["TEST"], "display_codes": ["TEST"], "name": "테스트 항목",
        "sources": [origin], "data_codes": {}, "description": [], "actions": [], "notes": [], "references": [],
        "check_points": [{"id": f"fixture:check_points:{i}", "text": f"명시된 점검 순서 {i+1}", "evidence": [origin]} for i in range(4)],
    }])


class BatchingClient:
    context_limit = 1000
    def __init__(self):
        self.calls = []
        self.overlong = False

    def count_tokens(self, messages):
        return 5000 if self.overlong else 100+200*len(json.loads(messages[1]["content"])["evidence"])

    def complete(self, messages, schema):
        self.calls.append(messages)
        entries = json.loads(messages[1]["content"])["evidence"]
        highlights = [{"evidence_id": e["id"], "quote": e["text"]} for e in reversed(entries)]
        return Completion(json.dumps({"status": "evidence", "highlights": highlights}), .01, self.count_tokens(messages), 50, 1000)


def test_batches_preserve_whole_facts_order_and_source_pages():
    client = BatchingClient()
    answer = LocalAnswerGenerator(Settings(), client).generate(source_fixture())
    assert answer["validation"]["valid"]
    assert answer["local_llm"]["batch_count"] == 4
    ids = [e["id"] for m in client.calls for e in json.loads(m[1]["content"])["evidence"]]
    assert ids == [f"fixture:check_points:{i}" for i in range(4)]
    assert [h["evidence_id"] for h in answer["highlights"]] == ids
    assert "PDF 7쪽 · 문서 6쪽" in answer["text"]
    assert all(json.loads(m[1]["content"])["pages"]["S1"]["pdf_page"] == 7 for m in client.calls)


def test_oversized_atomic_evidence_is_not_silently_cut():
    client = BatchingClient()
    client.overlong = True
    with pytest.raises(ContextBudgetError, match="필수 근거를 자르지"):
        LocalAnswerGenerator(Settings(), client).generate(source_fixture())
    assert client.calls == []


def test_unknown_code_does_not_need_running_llm():
    result = LocalAnswerGenerator(Settings(), object()).generate(Retrieval("E.UNKNOWN", "code", unknown_codes=["E.UNKNOWN"]))
    assert result["status"] == "insufficient" and result["local_llm"]["batch_count"] == 0


def test_symptom_procedure_order_is_restored_without_changing_hit_rank():
    from rag.answer_validator import evidence_units
    origin = {"source_pdf": "transport-fixture.pdf", "pdf_page": 7, "printed_page": "6"}
    rows = [{"id": f"row:{i}", "section": "2.6.1", "name": "테스트 증상", "area": "시험",
             "cause": "동일 원인", "action": f"점검 단계 {i}", "evidence": {**origin, "row": i}} for i in (3, 1, 2)]
    retrieval = Retrieval("question", "symptom", symptom_rows=rows, hits=[{"id": "row:3"}, {"id": "row:1"}, {"id": "row:2"}])
    answer = LocalAnswerGenerator(Settings()).generate(retrieval, evidence_only=True)
    assert answer["text"].find("점검 단계 1") < answer["text"].find("점검 단계 2") < answer["text"].find("점검 단계 3")
    assert [r["id"] for r in retrieval.symptom_rows] == ["row:3", "row:1", "row:2"]
    assert [h["id"] for h in retrieval.hits] == ["row:3", "row:1", "row:2"]
    units = evidence_units(retrieval)
    assert list(units) == ["row:1", "row:2", "row:3"]
    prompt = json.loads(make_messages("question", list(units.values()))[1]["content"])
    assert [e["retrieval_rank"] for e in prompt["evidence"]] == [2, 3, 1]


def test_local_failure_never_falls_back_to_external_api(monkeypatch):
    from rag.answer_generator import AnswerGenerator
    from rag.local_answer_generator import LocalAnswerGenerator
    def external(*args, **kwargs):
        pytest.fail("External LLM must never be called in local mode")
    def local(*args, **kwargs):
        raise LocalLLMError("local unavailable")
    monkeypatch.setattr(AnswerGenerator, "generate", external)
    monkeypatch.setattr(LocalAnswerGenerator, "generate", local)
    service = RAGService(replace(Settings(), llm_backend="local"), sqlite=object())
    service.retrieve = lambda _: source_fixture()
    with pytest.raises(LocalLLMError, match="local unavailable"):
        service.answer("question")
