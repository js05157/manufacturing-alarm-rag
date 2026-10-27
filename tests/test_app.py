from config import ROOT, Settings
import pytest


@pytest.fixture(autouse=True)
def isolated_chats(monkeypatch, tmp_path):
    from dataclasses import replace
    import config
    settings = replace(Settings(), chat_db=tmp_path/"chats.db")
    monkeypatch.setattr(config, "Settings", lambda: settings)
    return settings


def test_chat_session_and_unknown_code():
    if not Settings().sqlite.exists():
        pytest.skip("Local corpus not built")
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    assert not app.exception
    assert app.chat_input[0].placeholder == "알람 코드나 설비 증상을 입력하세요"
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
    assert "start_llm.ps1" in app.chat_message[1].error[0].value


def test_greeting_does_not_show_maintenance_instructions_or_llm_timing(monkeypatch):
    from streamlit.testing.v1 import AppTest
    from rag.local_answer_generator import LocalAnswerGenerator
    def forbidden(*args, **kwargs):
        pytest.fail("Greeting must not invoke the local model")
    monkeypatch.setattr(LocalAnswerGenerator, "generate", forbidden)
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    app.chat_input[0].set_value("안녕 넌 뭐하는 놈이야?").run()
    assert not app.exception and not app.error
    text = app.chat_message[1].markdown[0].value
    assert "도우미" in text and "FR-E800" in text
    assert "Pr.22" not in text and "PDF" not in text
    assert not any("로컬 모델 생성" in caption.value for caption in app.caption)


def test_room_creation_switching_history_isolation_and_page_reload(monkeypatch, isolated_chats):
    from streamlit.testing.v1 import AppTest
    from rag.pipeline import RAGService
    from rag.chat_store import ChatStore
    original = RAGService.answer
    calls = []

    def evidence_answer(self, question, evidence_only=False, history=None):
        answer = original(self, question, evidence_only=True, history=history)
        calls.append(answer)
        return answer

    monkeypatch.setattr(RAGService, "answer", evidence_answer)
    app = AppTest.from_file(str(ROOT/"app.py"), default_timeout=30).run()
    app.chat_input[0].set_value("E.OC1 원인").run()
    first = app.session_state["active_chat_id"]
    assert not app.exception and len(app.chat_message) == 2
    app.button(key="new_chat").click().run()
    assert app.session_state["active_chat_id"] is None and not app.chat_message
    assert len(ChatStore(isolated_chats.chat_db).rooms()) == 1
    app.chat_input[0].set_value("그럼 대처는?").run()
    second = app.session_state["active_chat_id"]
    assert second and second != first
    assert calls[-1]["mode"] == "direct"  # No leakage from room one.
    app.chat_input[0].set_value("E.OV1 원인").run()
    app.chat_input[0].set_value("그럼 대처는?").run()
    assert calls[-1]["retrieval"]["codes"] == ["E.OV1"]
    app.button(key=f"chat_{first}").click().run()
    assert len(app.chat_message) == 2 and app.chat_message[0].markdown[0].value == "E.OC1 원인"
    app.chat_input[0].set_value("그럼 대처는?").run()
    assert calls[-1]["retrieval"]["codes"] == ["E.OC1"]
    assert any("이전 질문 맥락" in caption.value for caption in app.caption)
    assert not app.exception and not app.error
    saved = ChatStore(isolated_chats.chat_db)
    assert len(saved.rooms()) == 2 and len(saved.messages(first)) == 4 and len(saved.messages(second)) == 6
    reload = AppTest.from_file(str(ROOT/"app.py"), default_timeout=30)
    reload.query_params["chat"] = first
    reload.run()
    assert not reload.exception and len(reload.chat_message) == 4
    assert reload.session_state["active_chat_id"] == first
    assert reload.button(key=f"chat_{first}").label == "E.OC1 원인"


def test_previous_session_messages_are_migrated_once(isolated_chats):
    from streamlit.testing.v1 import AppTest
    from rag.chat_store import ChatStore
    app = AppTest.from_file(str(ROOT/"app.py"), default_timeout=30)
    app.session_state["messages"] = [{"role":"user", "content":"E.THT 원인"}, {"role":"assistant", "content":"기존 대화"}]
    app.run()
    app.run()
    store = ChatStore(isolated_chats.chat_db)
    assert not app.exception and len(app.chat_message) == 2
    assert len(store.rooms()) == 1
    assert len(store.messages(app.session_state["active_chat_id"])) == 2


def test_chat_storage_cannot_write_into_manual_database(monkeypatch, tmp_path, isolated_chats):
    from dataclasses import replace
    import config
    from streamlit.testing.v1 import AppTest
    manual = tmp_path/"manual.db"
    sentinel = b"manual must remain unchanged"
    manual.write_bytes(sentinel)
    settings = replace(isolated_chats, sqlite=manual, chat_db=manual)
    monkeypatch.setattr(config, "Settings", lambda:settings)
    app = AppTest.from_file(str(ROOT/"app.py"), default_timeout=30).run()
    assert not app.exception and app.error
    assert "CHAT_DB_PATH" in app.error[0].value
    assert manual.read_bytes() == sentinel


def test_repeated_new_chat_is_an_unsaved_draft_and_preserves_old_empty_rooms(isolated_chats):
    from streamlit.testing.v1 import AppTest
    from rag.chat_store import ChatStore
    store = ChatStore(isolated_chats.chat_db)
    old_empty = store.create_room()
    saved = store.create_room()
    store.append(saved, "user", "기존 대화")
    app = AppTest.from_file(str(ROOT/"app.py"), default_timeout=30).run()
    assert app.session_state["active_chat_id"] is None
    assert "chat" not in app.query_params and not app.chat_message
    assert app.button(key=f"chat_{saved}")
    assert all(button.key != f"chat_{old_empty}" for button in app.button)
    for _ in range(4):
        app.button(key="new_chat").click().run()
    assert not app.exception and len(store.rooms()) == 2
    app.button(key=f"chat_{saved}").click().run()
    assert len(app.chat_message) == 1
    app.button(key="new_chat").click().run()
    assert not app.chat_message and app.session_state["messages"] == []
    app.chat_input[0].set_value("안녕하세요").run()
    assert not app.exception and not app.error
    assert len(store.rooms()) == 3 and len(store.rooms(include_empty=False)) == 2
    assert len(app.chat_message) == 2
    assert old_empty in {room["id"] for room in store.rooms()}


def test_starter_question_starts_one_saved_conversation(monkeypatch, isolated_chats):
    from streamlit.testing.v1 import AppTest
    from rag.pipeline import RAGService
    from rag.chat_store import ChatStore
    original = RAGService.answer

    def evidence_answer(self, question, evidence_only=False, history=None):
        return original(self, question, evidence_only=True, history=history)

    monkeypatch.setattr(RAGService, "answer", evidence_answer)
    app = AppTest.from_file(str(ROOT/"app.py"), default_timeout=30).run()
    app.button(key="starter_0_error_outline").click().run()
    assert not app.exception and not app.error
    assert len(app.chat_message) == 2
    assert app.chat_message[0].markdown[0].value == "E.OC1의 원인과 대처 방법"
    assert "PDF" in app.chat_message[1].markdown[0].value
    assert len(ChatStore(isolated_chats.chat_db).rooms()) == 1
