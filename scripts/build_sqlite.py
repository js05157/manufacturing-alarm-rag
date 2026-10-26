import argparse
import json
import os
import sqlite3
from pathlib import Path

from config import Settings, configure_console
from scripts.validate_data import load_verified

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE documents (sha256 TEXT PRIMARY KEY, filename TEXT NOT NULL);
CREATE TABLE alarms (code TEXT PRIMARY KEY, name TEXT NOT NULL, classification TEXT);
CREATE TABLE records (record_id TEXT PRIMARY KEY, document_sha256 TEXT NOT NULL REFERENCES documents(sha256), payload TEXT NOT NULL);
CREATE TABLE alarm_records (code TEXT REFERENCES alarms(code), record_id TEXT REFERENCES records(record_id), PRIMARY KEY(code,record_id));
CREATE TABLE alarm_items (record_id TEXT REFERENCES records(record_id), kind TEXT NOT NULL, position INTEGER NOT NULL, text TEXT NOT NULL, evidence TEXT NOT NULL, PRIMARY KEY(record_id,kind,position));
CREATE TABLE symptoms (section TEXT PRIMARY KEY, document_sha256 TEXT NOT NULL REFERENCES documents(sha256), payload TEXT NOT NULL);
CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def build(path, data, alarms, symptoms):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".building")
    # Only our explicitly named staging file is replaced, never the user's inputs.
    if temporary.exists():
        temporary.unlink()
    connection = sqlite3.connect(temporary)
    try:
        connection.executescript(SCHEMA)
        with connection:
            connection.execute("INSERT INTO documents VALUES (?,?)", (data["source_sha256"], data["source_pdf"]))
            for record in alarms:
                connection.execute("INSERT INTO records VALUES (?,?,?)", (record["record_id"], data["source_sha256"], json.dumps(record, ensure_ascii=False)))
                for code in record["codes"]:
                    connection.execute("INSERT OR IGNORE INTO alarms VALUES (?,?,?)", (code, record["name"], record["classification"]))
                    connection.execute("INSERT INTO alarm_records VALUES (?,?)", (code, record["record_id"]))
                for kind in ("description", "check_points", "actions", "references", "notes"):
                    for position, item in enumerate(record[kind]):
                        connection.execute("INSERT INTO alarm_items VALUES (?,?,?,?,?)", (record["record_id"], kind, position, item["text"], json.dumps(item["evidence"], ensure_ascii=False)))
            for record in symptoms:
                connection.execute("INSERT INTO symptoms VALUES (?,?,?)", (record["section"], data["source_sha256"], json.dumps(record, ensure_ascii=False)))
            connection.execute("INSERT INTO metadata VALUES ('source_sha256',?)", (data["source_sha256"],))
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("SQLite integrity check failed")
    finally:
        connection.close()
    os.replace(temporary, path)


def main():
    configure_console()
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, help="Initial validation only; omit for the complete supported corpus")
    p.add_argument("--output", type=Path, default=Settings().sqlite)
    args = p.parse_args()
    data, alarms, symptoms = load_verified()
    alarms = alarms[:args.limit] if args.limit else alarms
    build(args.output, data, alarms, symptoms)
    print(f"Built {len(alarms)} alarm records, {len(symptoms)} symptom sections: {args.output}")


if __name__ == "__main__":
    main()
