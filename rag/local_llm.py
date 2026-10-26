"""Loopback-only llama.cpp transport. No API key, proxy, redirect or retry."""
import re
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from time import perf_counter
from urllib.parse import urlsplit

import requests


class LocalLLMError(RuntimeError):
    pass


class ContextBudgetError(LocalLLMError):
    pass


@dataclass(frozen=True)
class Completion:
    content: str
    elapsed_seconds: float
    prompt_tokens: int
    completion_tokens: int
    context_limit: int


class LocalLLM:
    def __init__(self, settings, session=None):
        self.settings = settings
        url = urlsplit(settings.local_llm_url)
        if (url.scheme != "http" or url.hostname != "127.0.0.1" or not url.port
                or url.username or url.password or url.query or url.fragment
                or url.path.rstrip("/") not in ("", "/v1")):
            raise ValueError("LOCAL_LLM_URL은 http://127.0.0.1:포트/v1 형식이어야 합니다. 외부 LLM 서버는 허용하지 않습니다.")
        if not 0 < settings.local_llm_max_tokens < settings.local_llm_context <= 4096:
            raise ValueError("로컬 생성 토큰 < 컨텍스트 <= 4096으로 설정하세요.")
        if not 0 < settings.local_llm_temperature <= 2 or settings.local_llm_timeout <= 0:
            raise ValueError("로컬 temperature는 0 초과 2 이하, timeout은 양수여야 합니다.")
        self.origin = f"http://127.0.0.1:{url.port}"
        self.session = session or requests.Session()
        self.session.trust_env = False

    def _request(self, method, path, payload=None):
        try:
            response = self.session.request(method, self.origin+path, json=payload,
                timeout=(3, self.settings.local_llm_timeout), allow_redirects=False)
        except requests.Timeout:
            raise LocalLLMError("로컬 LLM 응답 시간이 초과되었습니다. 서버 로그와 LOCAL_LLM_TIMEOUT을 확인하세요.") from None
        except requests.ConnectionError:
            raise LocalLLMError("로컬 LLM 서버에 연결할 수 없습니다. PowerShell에서 .\\scripts\\start_llm.ps1을 실행하세요.") from None
        except requests.RequestException:
            raise LocalLLMError("로컬 LLM 통신에 실패했습니다. 서버 상태를 확인하세요.") from None
        if response.status_code != 200:
            if response.status_code == 503:
                message = "로컬 모델이 로딩 중이거나 서버가 요청을 처리할 수 없습니다. /health와 서버 로그를 확인하세요."
            elif response.status_code == 400:
                message = "로컬 LLM이 요청을 거부했습니다. 컨텍스트·모델명·JSON 출력 설정을 확인하세요."
            else:
                message = f"로컬 LLM HTTP {response.status_code} 오류입니다. 서버 로그를 확인하세요."
            raise LocalLLMError(message)
        try:
            data = response.json()
        except ValueError:
            raise LocalLLMError("로컬 LLM 서버가 올바른 JSON을 반환하지 않았습니다.") from None
        if not isinstance(data, dict):
            raise LocalLLMError("로컬 LLM 서버의 JSON 객체 형식이 올바르지 않습니다.")
        return data

    @cached_property
    def server(self):
        if self._request("GET", "/health").get("status") != "ok":
            raise LocalLLMError("로컬 LLM 모델이 아직 준비되지 않았습니다.")
        props = self._request("GET", "/props")
        if props.get("total_slots") != 1:
            raise LocalLLMError("로컬 서버는 --parallel 1로 실행하세요. 슬롯별 컨텍스트 예산을 확인할 수 없습니다.")
        models = self._request("GET", "/v1/models").get("data", [])
        if not isinstance(models, list) or self.settings.local_llm_model not in [m.get("id") for m in models if isinstance(m, dict)]:
            raise LocalLLMError("로컬 서버의 모델명이 LOCAL_LLM_MODEL과 다릅니다. 모델을 임의로 대체하지 않습니다.")
        model_path = props.get("model_path")
        if not isinstance(model_path, str) or Path(model_path).resolve() != self.settings.local_llm_model_path.resolve():
            raise LocalLLMError("로컬 서버가 다른 GGUF 파일을 사용하고 있습니다. LOCAL_LLM_MODEL_PATH를 확인하세요.")
        context = props.get("default_generation_settings", {}).get("n_ctx")
        if not isinstance(context, int) or context < 512:
            raise LocalLLMError("로컬 서버의 컨텍스트 크기를 확인할 수 없습니다.")
        return {"context": min(context, self.settings.local_llm_context), "model_path": model_path,
                "model": self.settings.local_llm_model, "build": props.get("build_info"), "slots": props.get("total_slots")}

    @property
    def context_limit(self):
        return self.server["context"]

    def count_tokens(self, messages):
        self.server
        formatted = self._request("POST", "/apply-template", {"messages": messages,
            "chat_template_kwargs": {"enable_thinking": False}, "reasoning_effort": "none"})
        if not isinstance(formatted.get("prompt"), str):
            raise LocalLLMError("로컬 chat template 응답에 prompt가 없습니다.")
        tokens = self._request("POST", "/tokenize", {"content": formatted["prompt"], "add_special": False, "parse_special": True}).get("tokens")
        if not isinstance(tokens, list) or not all(isinstance(t, int) for t in tokens):
            raise LocalLLMError("로컬 토크나이저 응답 형식이 올바르지 않습니다.")
        return len(tokens)

    def complete(self, messages, schema=None, max_tokens=None):
        started = perf_counter()
        max_tokens = max_tokens or self.settings.local_llm_max_tokens
        if not isinstance(max_tokens, int) or max_tokens < 1:
            raise ValueError("생성 토큰 제한은 양의 정수여야 합니다.")
        prompt_tokens = self.count_tokens(messages)
        if prompt_tokens+max_tokens+self.settings.local_llm_margin > self.context_limit:
            raise ContextBudgetError("질문과 근거가 로컬 4096토큰 예산을 초과했습니다. 원문을 임의로 자르지 않고 요청을 중단했습니다.")
        payload = {"model": self.settings.local_llm_model, "messages": messages,
            "max_tokens": max_tokens, "temperature": self.settings.local_llm_temperature,
            "top_p": 0.8, "top_k": 20, "min_p": 0, "seed": 42, "stream": False,
            "chat_template_kwargs": {"enable_thinking": False}, "reasoning_effort": "none",
            "cache_prompt": True}
        if schema:
            payload["response_format"] = {"type": "json_object", "schema": schema}
        data = self._request("POST", "/v1/chat/completions", payload)
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise LocalLLMError("로컬 LLM 응답에 올바른 choices가 없습니다.")
        choice = choices[0]
        if choice.get("finish_reason") != "stop":
            raise LocalLLMError("로컬 LLM 출력이 잘렸거나 중단되었습니다. 생성 토큰 제한과 서버 로그를 확인하세요.")
        message = choice.get("message")
        text = message.get("content") if isinstance(message, dict) else None
        if not isinstance(text, str) or not text.strip():
            raise LocalLLMError("로컬 LLM이 비어 있거나 잘못된 답변을 반환했습니다.")
        # Remove only an empty leading thinking wrapper, never actual answer text.
        text = re.sub(r"^\s*<think>\s*</think>\s*", "", text, count=1).strip()
        if "<think>" in text or "</think>" in text:
            raise LocalLLMError("로컬 LLM에 추론 태그가 남아 있습니다. --reasoning off 설정을 확인하세요.")
        usage = data.get("usage")
        if not isinstance(usage, dict) or any(not isinstance(usage.get(k), int) or usage[k] < 0 for k in ("prompt_tokens", "completion_tokens")):
            raise LocalLLMError("로컬 LLM의 토큰 사용량을 검증할 수 없습니다.")
        if usage["prompt_tokens"]+usage["completion_tokens"] > self.context_limit:
            raise ContextBudgetError("서버의 실제 토큰 사용량이 컨텍스트 예산을 초과했습니다.")
        if data.get("model") != self.settings.local_llm_model:
            raise LocalLLMError("응답 모델명이 요청 모델명과 다릅니다.")
        return Completion(text, perf_counter()-started, usage["prompt_tokens"], usage["completion_tokens"], self.context_limit)
