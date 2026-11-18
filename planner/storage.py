"""SQLite persistence for plans, execution logs, and compact session memory."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from planner.events import ExecutionEvent


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PlannerDatabase:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS maintenance_plans (
                    id TEXT PRIMARY KEY,
                    session_id TEXT,
                    title TEXT NOT NULL,
                    alarm_code TEXT,
                    location TEXT,
                    plan_date TEXT NOT NULL,
                    start_time TEXT NOT NULL,
                    end_time TEXT NOT NULL,
                    notes TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS plans_date_time
                    ON maintenance_plans(plan_date, start_time, end_time);

                CREATE TABLE IF NOT EXISTS execution_sessions (
                    session_id TEXT PRIMARY KEY,
                    user_request TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    completed_at TEXT
                );
                CREATE TABLE IF NOT EXISTS execution_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL REFERENCES execution_sessions(session_id) ON DELETE CASCADE,
                    sequence INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    tool_name TEXT,
                    duration_ms REAL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(session_id, sequence)
                );
                CREATE INDEX IF NOT EXISTS events_session ON execution_events(session_id, sequence);

                CREATE TABLE IF NOT EXISTS planner_memory (
                    session_id TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

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


class PlanStore:
    FIELDS = {"title", "alarm_code", "location", "plan_date", "start_time", "end_time", "notes"}

    def __init__(self, database: PlannerDatabase):
        self.database = database

    @staticmethod
    def _validate(values: dict[str, Any]) -> None:
        required = ("title", "plan_date", "start_time", "end_time")
        if any(not isinstance(values.get(name), str) or not values[name].strip() for name in required):
            raise ValueError("계획 제목, 날짜, 시작 시각, 종료 시각은 필수입니다.")
        try:
            datetime.fromisoformat(values["plan_date"])
            start = datetime.strptime(values["start_time"], "%H:%M").time()
            end = datetime.strptime(values["end_time"], "%H:%M").time()
        except ValueError:
            raise ValueError("날짜는 YYYY-MM-DD, 시각은 HH:MM 형식이어야 합니다.") from None
        if start >= end:
            raise ValueError("종료 시각은 시작 시각보다 늦어야 합니다.")

    def _overlaps(self, values: dict[str, Any], exclude_id: str | None = None) -> list[dict[str, Any]]:
        query = """
            SELECT id,title,plan_date,start_time,end_time FROM maintenance_plans
            WHERE plan_date=? AND start_time < ? AND end_time > ?
        """
        params: list[Any] = [values["plan_date"], values["end_time"], values["start_time"]]
        if exclude_id:
            query += " AND id<>?"
            params.append(exclude_id)
        with self.database.connection() as db:
            return [dict(row) for row in db.execute(query + " ORDER BY start_time,id", params)]

    def create(self, values: dict[str, Any], *, session_id: str | None = None) -> dict[str, Any]:
        self._validate(values)
        plan_id, now = uuid4().hex, _now()
        overlaps = self._overlaps(values)
        row = {
            "id": plan_id,
            "session_id": session_id,
            "title": values["title"].strip(),
            "alarm_code": values.get("alarm_code"),
            "location": values.get("location"),
            "plan_date": values["plan_date"],
            "start_time": values["start_time"],
            "end_time": values["end_time"],
            "notes": values.get("notes", ""),
            "created_at": now,
            "updated_at": now,
        }
        with self.database.connection() as db:
            db.execute(
                "INSERT INTO maintenance_plans VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                tuple(row.values()),
            )
        return {"plan": row, "overlaps": overlaps}

    def list(self) -> list[dict[str, Any]]:
        with self.database.connection() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT * FROM maintenance_plans ORDER BY plan_date,start_time,created_at"
                )
            ]

    def get(self, plan_id: str) -> dict[str, Any] | None:
        with self.database.connection() as db:
            row = db.execute("SELECT * FROM maintenance_plans WHERE id=?", (plan_id,)).fetchone()
        return dict(row) if row else None

    def update(self, plan_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
        current = self.get(plan_id)
        if not current:
            return None
        unknown = set(changes) - self.FIELDS
        if unknown:
            raise ValueError(f"수정할 수 없는 계획 필드입니다: {', '.join(sorted(unknown))}")
        merged = {**current, **changes}
        self._validate(merged)
        overlaps = self._overlaps(merged, exclude_id=plan_id)
        if changes:
            assignments = ",".join(f"{name}=?" for name in changes) + ",updated_at=?"
            values = [changes[name] for name in changes] + [_now(), plan_id]
            with self.database.connection() as db:
                db.execute(f"UPDATE maintenance_plans SET {assignments} WHERE id=?", values)
        return {"plan": self.get(plan_id), "overlaps": overlaps}

    def delete(self, plan_id: str) -> bool:
        with self.database.connection() as db:
            cursor = db.execute("DELETE FROM maintenance_plans WHERE id=?", (plan_id,))
        return cursor.rowcount == 1


class ExecutionLogStore:
    def __init__(self, database: PlannerDatabase):
        self.database = database

    def start_session(self, session_id: str, user_request: str) -> None:
        with self.database.connection() as db:
            db.execute(
                "INSERT INTO execution_sessions(session_id,user_request,status,created_at) VALUES (?,?,?,?)",
                (session_id, user_request, "running", _now()),
            )

    def finish_session(self, session_id: str, status: str) -> None:
        with self.database.connection() as db:
            db.execute(
                "UPDATE execution_sessions SET status=?,completed_at=? WHERE session_id=?",
                (status, _now(), session_id),
            )

    def append_event(self, event: ExecutionEvent) -> None:
        with self.database.connection() as db:
            sequence = db.execute(
                "SELECT COALESCE(MAX(sequence),0)+1 FROM execution_events WHERE session_id=?",
                (event.session_id,),
            ).fetchone()[0]
            db.execute(
                """INSERT INTO execution_events(
                    session_id,sequence,event_type,stage,tool_name,duration_ms,payload,created_at
                ) VALUES (?,?,?,?,?,?,?,?)""",
                (
                    event.session_id,
                    sequence,
                    event.event_type,
                    event.stage,
                    event.tool_name,
                    event.duration_ms,
                    json.dumps(event.payload, ensure_ascii=False),
                    event.created_at,
                ),
            )

    def list_sessions(self) -> list[dict[str, Any]]:
        with self.database.connection() as db:
            rows = db.execute(
                """SELECT s.*,COUNT(e.id) AS event_count
                FROM execution_sessions s LEFT JOIN execution_events e USING(session_id)
                GROUP BY s.session_id ORDER BY s.created_at DESC"""
            )
            return [dict(row) for row in rows]

    def detail(self, session_id: str) -> dict[str, Any] | None:
        with self.database.connection() as db:
            session = db.execute(
                "SELECT * FROM execution_sessions WHERE session_id=?", (session_id,)
            ).fetchone()
            if not session:
                return None
            events = db.execute(
                "SELECT * FROM execution_events WHERE session_id=? ORDER BY sequence", (session_id,)
            ).fetchall()
        return {
            "session": dict(session),
            "events": [{**dict(row), "payload": json.loads(row["payload"])} for row in events],
        }

    def delete(self, session_id: str) -> bool:
        with self.database.connection() as db:
            cursor = db.execute("DELETE FROM execution_sessions WHERE session_id=?", (session_id,))
        return cursor.rowcount == 1


class MemoryStore:
    def __init__(self, database: PlannerDatabase):
        self.database = database

    def get(self, session_id: str) -> dict[str, Any]:
        with self.database.connection() as db:
            row = db.execute("SELECT state FROM planner_memory WHERE session_id=?", (session_id,)).fetchone()
        return json.loads(row[0]) if row else {}

    def put(self, session_id: str, state: dict[str, Any]) -> None:
        encoded = json.dumps(state, ensure_ascii=False)
        with self.database.connection() as db:
            db.execute(
                """INSERT INTO planner_memory VALUES (?,?,?)
                ON CONFLICT(session_id) DO UPDATE SET state=excluded.state,updated_at=excluded.updated_at""",
                (session_id, encoded, _now()),
            )
