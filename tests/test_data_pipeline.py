import copy
import sqlite3

import pytest

from config import ROOT
from rag.sqlite_retriever import SQLiteRetriever
from scripts.build_sqlite import build
from scripts.common import cell_text, items, read_json
from scripts.parse_alarms import normalize_code, parse


def test_cell_centres_and_bullet_order():
    words = [(0, 0, 10, 20, "first", 0, 0, 0), (0, 11, 10, 31, "second", 1, 0, 0)]
    assert cell_text(words, [0, 0, 11, 20]) == "first"
    assert items("• 항목 하나\n이어지는 줄\n• 항목 둘") == ["항목 하나 이어지는 줄", "항목 둘"]
    assert items("───────") == []


def test_code_normalization_keeps_punctuation():
    assert normalize_code(" e.oc1 ") == "E.OC1"
    assert normalize_code("E. 5") == "E.5"
    assert normalize_code("EOC1") != normalize_code("E.OC1")
    assert normalize_code("Err.") != normalize_code("Er1")


@pytest.fixture
def local_dataset():
    path = ROOT / "data/processed/alarms.json"
    if not path.exists():
        pytest.skip("Local licensed PDF corpus not available")
    return read_json(path)


def test_source_specific_ranges_and_variants(local_dataset):
    records = local_dataset["alarms"]
    codes = {c for r in records for c in r["codes"]}
    assert len(records) == 75 and len(codes) == 88
    assert {"HP1", "HP2", "E.16", "E.20", "E.5", "E.7", "E.MB7"} <= codes
    assert sum("E.SAF" in r["codes"] for r in records) == 2
    assert len(local_dataset["symptoms"]) == 14
    dc = {c: v for r in records for c, v in r["data_codes"].items()}
    assert dc["E.OC2"]["value"] == "17 (H11)"
    assert dc["OLV"]["value"] == "2 (H02)"
    assert dc["E.OA"]["consistent"] is False


def test_sqlite_rebuild_and_exact_lookup(tmp_path, local_dataset):
    path = tmp_path / "test.db"
    data = local_dataset
    for _ in range(2):
        build(path, data, data["alarms"], data["symptoms"])
    search = SQLiteRetriever(path)
    assert len(search.codes()) == 88
    assert len(search.get("e.saf")) == 2
    assert len(search.get("E.OC1")) == 1
    assert search.get("E.OC10") == []
    assert search.get("EOC1") == []
    assert search.get("' OR 1=1 --") == []
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert db.execute("SELECT COUNT(*) FROM records").fetchone()[0] == 75


def test_modified_item_fails_source_verification(local_dataset):
    from scripts.validate_data import verify
    from config import Settings
    data = copy.deepcopy(local_dataset)
    data["alarms"] = data["alarms"][:1]
    data["symptoms"] = []
    data["alarms"][0]["actions"][0]["text"] = "This fabricated instruction is not in the PDF."
    result = verify(data, Settings().pdf)
    assert result["accepted"] == []
    assert "source mismatch" in str(result["rejected"])

