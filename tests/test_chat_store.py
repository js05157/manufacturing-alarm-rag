import sqlite3

import pytest

from rag.chat_store import ChatStore


def test_rooms_and_messages_persist_in_order_and_remain_isolated(tmp_path):
    path = tmp_path / "chats.db"
    store = ChatStore(path)
    a, b = store.create_room(), store.create_room()
    store.append(a, "user", "E.OC1 원인")
    store.append(a, "assistant", "답변", {"conversation_context": {"codes": ["E.OC1"]}, "elapsed_seconds": .5})
    store.append(b, "user", "E.OV1 원인")
    reopened = ChatStore(path)
    assert [room["id"] for room in reopened.rooms()] == [b, a]
    assert [m["role"] for m in reopened.messages(a)] == ["user", "assistant"]
    assert reopened.messages(a)[1]["metadata"]["conversation_context"]["codes"] == ["E.OC1"]
    assert reopened.messages(b)[0]["content"] == "E.OV1 원인"
    assert reopened.messages("missing") == []
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_title_uses_first_question_and_handles_sql_as_text(tmp_path):
    store = ChatStore(tmp_path/"chats.db")
    room = store.create_room()
    question = "E.THT\n" + "긴 질문 "*20 + "'; DROP TABLE chat_rooms; --"
    store.append(room, "user", question)
    title = store.rooms()[0]["title"]
    assert len(title) == 29 and title.endswith("…") and "\n" not in title
    store.append(room, "user", "다음 질문")
    assert store.rooms()[0]["title"] == title
    assert store.messages(room)[0]["content"] == question


def test_invalid_message_or_missing_room_never_creates_partial_records(tmp_path):
    store = ChatStore(tmp_path/"chats.db")
    room = store.create_room()
    for role, content in [("system", "test"), ("user", " "), ("assistant", None)]:
        with pytest.raises(ValueError):
            store.append(room, role, content)
    with pytest.raises(ValueError, match="채팅방"):
        store.append("missing", "user", "test")
    assert store.messages(room) == []


def test_nonempty_room_listing_hides_empty_rows_without_deleting_them(tmp_path):
    store = ChatStore(tmp_path/"chats.db")
    empty, started = store.create_room(), store.create_room()
    assert store.rooms(include_empty=False) == []
    store.append(started, "user", "E.OC1 원인")
    assert [room["id"] for room in store.rooms(include_empty=False)] == [started]
    assert {room["id"] for room in store.rooms()} == {empty, started}


def test_equal_timestamps_use_message_sequence_for_room_recency(monkeypatch, tmp_path):
    from datetime import datetime, timezone
    from types import SimpleNamespace
    import rag.chat_store as module
    fixed=datetime(2026,10,28,tzinfo=timezone.utc)
    monkeypatch.setattr(module,"datetime",SimpleNamespace(now=lambda _:fixed))
    store=ChatStore(tmp_path/"chats.db")
    a,b=store.create_room(),store.create_room()
    store.append(a,"user","first")
    store.append(b,"user","second")
    assert [r["id"] for r in store.rooms()] == [b,a]
    store.append(a,"assistant","latest")
    assert [r["id"] for r in store.rooms()] == [a,b]
