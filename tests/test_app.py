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
