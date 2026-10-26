import json
import sqlite3
from pathlib import Path

from scripts.parse_alarms import normalize_code


class SQLiteRetriever:
    def __init__(self, path):
        self.path = Path(path)
        if not self.path.is_file():
            raise FileNotFoundError("검증된 데이터베이스가 없습니다. 먼저 데이터 구축 명령을 실행하세요.")

    def _connect(self):
        return sqlite3.connect(self.path.resolve().as_uri()+"?mode=ro", uri=True)

    def codes(self):
        with self._connect() as db:
            return {r[0] for r in db.execute("SELECT code FROM alarms")}

    def get(self, code):
        with self._connect() as db:
            rows = db.execute("SELECT r.payload FROM records r JOIN alarm_records a ON r.record_id=a.record_id WHERE a.code=? ORDER BY r.record_id", (normalize_code(code),)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def symptom(self, section):
        with self._connect() as db:
            row = db.execute("SELECT payload FROM symptoms WHERE section=?", (section,)).fetchone()
        return json.loads(row[0]) if row else None

    def source_hash(self):
        with self._connect() as db:
            return db.execute("SELECT value FROM metadata WHERE key='source_sha256'").fetchone()[0]
