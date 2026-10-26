from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest
from openai import RateLimitError

from config import Settings
from rag.answer_generator import AnswerGenerator, llm_error_message
from rag.pipeline import Retrieval


def provider_error(body):
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    response = httpx.Response(429, request=request)
    return RateLimitError("sensitive-provider-message", response=response, body=body)


@pytest.mark.parametrize("code,expected", [
    ("credit_balance_exhausted", "선불 크레딧"),
    ("insufficient_quota", "잔액 또는 사용 할당량"),
    ("organization_spend_limit_exceeded", "조직의 API 지출 한도"),
    ("project_spend_limit_exceeded", "프로젝트의 API 지출 한도"),
    ("organization_usage_limit_exceeded", "허용된 API 사용 한도"),
    ("billing_hard_limit_reached", "API 결제 한도"),
    ("usage_limit_exceeded", "API 사용 한도"),
    ("rate_limit_exceeded", "요청 속도 제한"),
    ("slow_down", "너무 빠르게 증가"),
])
def test_specific_error_categories_without_provider_secrets(code, expected):
    for body in ({"code": code}, {"error": {"code": code}}):
        message = llm_error_message(provider_error(body))
        assert expected in message
        assert "sensitive-provider-message" not in message


@pytest.mark.parametrize("body", [{}, {"code": "secret-in-unknown-code"}, {"code": ["unexpected"]}, {"error": "unexpected"}])
def test_unknown_429_does_not_guess_temporary_throttling(body):
    message = llm_error_message(provider_error(body))
    assert "확정할 수 없습니다" in message
    assert "secret-in-unknown-code" not in message
    assert "sensitive-provider-message" not in message


def test_billing_error_is_not_retried_or_replaced():
    # Isolated transport fixture; never loaded into the manual corpus.
    retrieval = Retrieval("test", "code", records=[{
        "record_id": "test", "name": "synthetic unit", "codes": ["TEST"],
        "description": [{"id": "test:description:0", "text": "synthetic transport fixture", "evidence": []}],
        "check_points": [], "actions": [], "references": [], "notes": [],
    }])
    calls = []
    def create(**kwargs):
        calls.append(kwargs)
        raise provider_error({"code": "credit_balance_exhausted"})
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    settings = replace(Settings(), llm_model="test-model", llm_api_key="test-placeholder")
    with pytest.raises(RuntimeError, match="선불 크레딧"):
        AnswerGenerator(settings, client).generate(retrieval)
    assert len(calls) == 1
    assert calls[0]["model"] == "test-model"
