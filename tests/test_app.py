from config import ROOT, Settings
import pytest


def test_chat_session_and_unknown_code():
    if not Settings().sqlite.exists():
        pytest.skip("Local corpus not built")
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    assert not app.exception
    assert app.title[0].value == "Manufacturing Alarm RAG"
    app.chat_input[0].set_value("E.OC999 알람").run()
    assert not app.exception
    assert len(app.chat_message) == 2
    assert "검증된 근거를 찾지 못했습니다" in app.chat_message[1].markdown[0].value
    app.run()
    assert len(app.chat_message) == 2


def test_local_server_failure_keeps_app_and_history_alive(monkeypatch):
    from streamlit.testing.v1 import AppTest
    from rag.local_llm import LocalLLMError
    from rag.pipeline import RAGService
    def unavailable(*args, **kwargs):
        raise LocalLLMError("로컬 LLM 서버에 연결할 수 없습니다. start_llm.ps1을 실행하세요.")
    monkeypatch.setattr(RAGService, "answer", unavailable)
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    app.chat_input[0].set_value("E.THT 원인").run()
    assert not app.exception
    assert "start_llm.ps1" in app.error[0].value
    app.run()
    assert not app.exception and len(app.chat_message) == 2
    assert "start_llm.ps1" in app.chat_message[1].markdown[0].value
