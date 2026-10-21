import json
import sqlite3

import pytest

from kotonoha.db import connect, ingest_documents, initialize
from kotonoha.preprocessor import load_documents


def test_schema_indexes_and_idempotent_initialization(connection):
    initialize(connection)
    tables = {
        r[0]
        for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {
        "documents",
        "sentences",
        "suw_tokens",
        "luw_tokens",
        "luw_members",
    } <= tables
    indexes = {
        r[0]
        for r in connection.execute("SELECT name FROM sqlite_master WHERE type='index'")
    }
    assert {
        "idx_suw_lemma",
        "idx_suw_pos1",
        "idx_luw_lemma",
        "idx_luw_pos",
        "idx_luw_members_suw",
    } <= indexes
    assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_relationships_complete_ordered_partition(corpus):
    rows = corpus.execute("""SELECT l.surface, m.position, s.surface AS suw
        FROM luw_tokens l JOIN luw_members m ON l.id=m.luw_id
        JOIN suw_tokens s ON s.id=m.suw_id WHERE l.surface='東京都現代美術館'
        ORDER BY m.position""").fetchall()
    assert [(r["position"], r["suw"]) for r in rows] == list(
        enumerate(["東京", "都", "現代", "美術", "館"], 1)
    )
    assert (
        corpus.execute("SELECT count(*) FROM suw_tokens").fetchone()[0]
        == corpus.execute("SELECT count(*) FROM luw_members").fetchone()[0]
    )
    assert corpus.execute("PRAGMA foreign_key_check").fetchall() == []
    assert corpus.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    metadata = json.loads(
        corpus.execute("SELECT metadata_json FROM documents").fetchone()[0]
    )
    assert metadata["analysis_backends"] == ["fallback"] * 3


@pytest.mark.parametrize(
    "operation",
    ["foreign", "position", "duplicate", "cross-sentence", "update-cross-sentence"],
)
def test_invalid_members_are_rejected(corpus, operation):
    member = corpus.execute("SELECT * FROM luw_members LIMIT 1").fetchone()
    other = corpus.execute(
        """SELECT s.id FROM suw_tokens s JOIN luw_tokens l ON l.id=?
        WHERE s.sentence_id != l.sentence_id LIMIT 1""",
        (member["luw_id"],),
    ).fetchone()[0]
    with pytest.raises(sqlite3.IntegrityError):
        if operation == "foreign":
            corpus.execute("INSERT INTO luw_members VALUES (99999,99999,1)")
        elif operation == "position":
            corpus.execute(
                "UPDATE luw_members SET position=0 WHERE luw_id=? AND position=1",
                (member["luw_id"],),
            )
        elif operation == "duplicate":
            corpus.execute(
                "INSERT INTO luw_members VALUES (?, ?, 99)",
                (member["luw_id"], member["suw_id"]),
            )
        elif operation == "cross-sentence":
            corpus.execute(
                "INSERT INTO luw_members VALUES (?, ?, 99)", (member["luw_id"], other)
            )
        else:
            corpus.execute(
                "UPDATE luw_members SET suw_id=? WHERE luw_id=? AND position=1",
                (other, member["luw_id"]),
            )


def test_document_char_count_constraint(connection):
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO documents(filename,source_type,original_text,char_count) "
            "VALUES ('a','txt','本文',1)"
        )


def test_atomic_ingest_rolls_back_all_rows(connection, analyzer, tmp_path):
    path = tmp_path / "input.csv"
    path.write_text("text\n成功。\n失敗。\n", encoding="utf-8")

    class FailingAnalyzer:
        def analyze(self, sentence):
            if "失敗" in sentence.text:
                raise RuntimeError("injected failure")
            return analyzer.analyze(sentence)

    with pytest.raises(RuntimeError, match="injected"):
        ingest_documents(connection, load_documents(path), FailingAnalyzer())
    for table in ("documents", "sentences", "suw_tokens", "luw_tokens", "luw_members"):
        assert connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
    assert (
        ingest_documents(connection, load_documents(path), analyzer)["documents"] == 2
    )


def test_raw_original_ruby_metadata_and_empty_document(connection, analyzer, tmp_path):
    path = tmp_path / "input.txt"
    original = "｜漢字《かんじ》\r\n次。"
    path.write_bytes(original.encode("utf-8"))
    ingest_documents(connection, load_documents(path), analyzer)
    row = connection.execute("SELECT * FROM documents").fetchone()
    assert row["original_text"] == original
    assert row["char_count"] == len(original)
    assert json.loads(row["metadata_json"])["rubies"][0]["reading"] == "かんじ"
    empty = tmp_path / "empty.txt"
    empty.write_bytes(b"")
    assert ingest_documents(connection, load_documents(empty), analyzer) == {
        "documents": 1,
        "sentences": 0,
        "suw": 0,
        "luw": 0,
    }


def test_readonly_missing_db_does_not_create_file(tmp_path):
    path = tmp_path / "missing.db"
    with pytest.raises(sqlite3.OperationalError):
        connect(path, readonly=True)
    assert not path.exists()
