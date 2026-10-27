"""Local chat persistence, kept separate from the verified manual databases."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


class ChatStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS chat_rooms (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS chat_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    room_id TEXT NOT NULL REFERENCES chat_rooms(id),
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                    content TEXT NOT NULL, metadata TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS chat_messages_room ON chat_messages(room_id, id);
            """)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def create_room(self):
        room_id = uuid4().hex
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as db:
            db.execute("INSERT INTO chat_rooms VALUES (?,?,?,?)", (room_id, "새 채팅", now, now))
        return room_id

    def rooms(self, *, include_empty=True):
        with self.connection() as db:
            condition = "" if include_empty else " WHERE EXISTS (SELECT 1 FROM chat_messages m WHERE m.room_id=chat_rooms.id)"
            return [dict(row) for row in db.execute("SELECT * FROM chat_rooms"+condition+" ORDER BY updated_at DESC, id")]

    def messages(self, room_id):
        with self.connection() as db:
            rows = db.execute("SELECT * FROM chat_messages WHERE room_id=? ORDER BY id", (room_id,)).fetchall()
        return [{**dict(row), "metadata": json.loads(row["metadata"])} for row in rows]

    def append(self, room_id, role, content, metadata=None):
        if role not in ("user", "assistant") or not isinstance(content, str) or not content.strip():
            raise ValueError("저장할 대화의 역할과 내용을 확인해 주세요.")
        now = datetime.now(timezone.utc).isoformat()
        encoded = json.dumps(metadata or {}, ensure_ascii=False)
        with self.connection() as db:
            if not db.execute("SELECT 1 FROM chat_rooms WHERE id=?", (room_id,)).fetchone():
                raise ValueError("채팅방을 찾을 수 없습니다.")
            first_user = role == "user" and not db.execute(
                "SELECT 1 FROM chat_messages WHERE room_id=? AND role='user' LIMIT 1", (room_id,)).fetchone()
            db.execute("INSERT INTO chat_messages(room_id,role,content,metadata,created_at) VALUES (?,?,?,?,?)",
                       (room_id, role, content, encoded, now))
            if first_user:
                title = " ".join(content.split())
                title = title[:28]+("…" if len(title) > 28 else "")
                db.execute("UPDATE chat_rooms SET title=?, updated_at=? WHERE id=?", (title, now, room_id))
            else:
                db.execute("UPDATE chat_rooms SET updated_at=? WHERE id=?", (now, room_id))
