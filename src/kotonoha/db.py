"""SQLiteスキーマとファイル単位の原子的な取り込み。"""

import json
import sqlite3
from collections.abc import Iterable
from dataclasses import asdict
from pathlib import Path

from kotonoha.analyzer import Analyzer
from kotonoha.preprocessor import Document

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    source_type TEXT NOT NULL CHECK(source_type IN ('txt','csv','tsv')),
    original_text TEXT NOT NULL,
    char_count INTEGER NOT NULL CHECK(char_count = length(original_text)),
    metadata_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS sentences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    sentence_index INTEGER NOT NULL CHECK(sentence_index >= 0),
    start_char INTEGER NOT NULL CHECK(start_char >= 0),
    end_char INTEGER NOT NULL CHECK(end_char > start_char),
    text TEXT NOT NULL,
    UNIQUE(document_id, sentence_index)
);
CREATE TABLE IF NOT EXISTS suw_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sentence_id INTEGER NOT NULL REFERENCES sentences(id) ON DELETE CASCADE,
    token_index INTEGER NOT NULL CHECK(token_index >= 0),
    surface TEXT NOT NULL,
    pos1 TEXT, pos2 TEXT, pos3 TEXT, pos4 TEXT,
    c_type TEXT, c_form TEXT, lemma TEXT, lemma_reading TEXT,
    pronunciation TEXT, orth_token TEXT, goshu TEXT,
    start_char INTEGER NOT NULL CHECK(start_char >= 0),
    end_char INTEGER NOT NULL CHECK(end_char > start_char),
    UNIQUE(sentence_id, token_index)
);
CREATE TABLE IF NOT EXISTS luw_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sentence_id INTEGER NOT NULL REFERENCES sentences(id) ON DELETE CASCADE,
    luw_index INTEGER NOT NULL CHECK(luw_index >= 0),
    surface TEXT NOT NULL,
    pos TEXT NOT NULL,
    lemma TEXT,
    start_char INTEGER NOT NULL CHECK(start_char >= 0),
    end_char INTEGER NOT NULL CHECK(end_char > start_char),
    UNIQUE(sentence_id, luw_index)
);
CREATE TABLE IF NOT EXISTS luw_members (
    luw_id INTEGER NOT NULL REFERENCES luw_tokens(id) ON DELETE CASCADE,
    suw_id INTEGER NOT NULL UNIQUE REFERENCES suw_tokens(id) ON DELETE CASCADE,
    position INTEGER NOT NULL CHECK(position >= 1),
    PRIMARY KEY(luw_id, position)
);
CREATE INDEX IF NOT EXISTS idx_suw_lemma ON suw_tokens(lemma);
CREATE INDEX IF NOT EXISTS idx_suw_pos1 ON suw_tokens(pos1);
CREATE INDEX IF NOT EXISTS idx_luw_lemma ON luw_tokens(lemma);
CREATE INDEX IF NOT EXISTS idx_luw_pos ON luw_tokens(pos);
CREATE INDEX IF NOT EXISTS idx_luw_members_suw ON luw_members(suw_id);
CREATE INDEX IF NOT EXISTS idx_sentences_document ON sentences(document_id);
CREATE TRIGGER IF NOT EXISTS members_sentence_insert
BEFORE INSERT ON luw_members
WHEN (SELECT sentence_id FROM luw_tokens WHERE id=NEW.luw_id)
  != (SELECT sentence_id FROM suw_tokens WHERE id=NEW.suw_id)
BEGIN SELECT RAISE(ABORT, 'members must belong to the same sentence'); END;
CREATE TRIGGER IF NOT EXISTS members_sentence_update
BEFORE UPDATE ON luw_members
WHEN (SELECT sentence_id FROM luw_tokens WHERE id=NEW.luw_id)
  != (SELECT sentence_id FROM suw_tokens WHERE id=NEW.suw_id)
BEGIN SELECT RAISE(ABORT, 'members must belong to the same sentence'); END;
"""


def connect(
    path: str | Path = "kotonoha.sqlite3", *, readonly: bool = False
) -> sqlite3.Connection:
    if readonly:
        connection = sqlite3.connect(
            Path(path).resolve().as_uri() + "?mode=ro", uri=True
        )
    else:
        connection = sqlite3.connect(str(path))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA)


def _insert(connection: sqlite3.Connection, table: str, values: dict) -> int:
    # tableと列名は内部の固定スキーマだけから渡します。
    columns = ",".join(values)
    placeholders = ",".join("?" for _ in values)
    sql = f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"
    return connection.execute(sql, tuple(values.values())).lastrowid


def ingest_documents(
    connection: sqlite3.Connection, documents: Iterable[Document], analyzer: Analyzer
) -> dict[str, int]:
    counts = {"documents": 0, "sentences": 0, "suw": 0, "luw": 0}
    with connection:
        for document in documents:
            analyses = [analyzer.analyze(sentence) for sentence in document.sentences]
            metadata = {
                **document.metadata,
                "analysis_backends": [a.backend for a in analyses],
            }
            doc_id = _insert(
                connection,
                "documents",
                {
                    "filename": document.filename,
                    "source_type": document.source_type,
                    "original_text": document.original_text,
                    "char_count": len(document.original_text),
                    "metadata_json": json.dumps(metadata, ensure_ascii=False),
                },
            )
            counts["documents"] += 1
            for index, (sentence, analysis) in enumerate(
                zip(document.sentences, analyses, strict=True)
            ):
                sentence_id = _insert(
                    connection,
                    "sentences",
                    {
                        "document_id": doc_id,
                        "sentence_index": index,
                        "start_char": sentence.start_char,
                        "end_char": sentence.end_char,
                        "text": sentence.text,
                    },
                )
                ids = {}
                for token in analysis.suw:
                    ids[token.token_index] = _insert(
                        connection,
                        "suw_tokens",
                        {
                            "sentence_id": sentence_id,
                            **asdict(token),
                        },
                    )
                for token in analysis.luw:
                    values = asdict(token)
                    members = values.pop("members")
                    luw_id = _insert(
                        connection, "luw_tokens", {"sentence_id": sentence_id, **values}
                    )
                    connection.executemany(
                        "INSERT INTO luw_members VALUES (?, ?, ?)",
                        [
                            (luw_id, ids[member], position)
                            for position, member in enumerate(members, 1)
                        ],
                    )
                counts["sentences"] += 1
                counts["suw"] += len(analysis.suw)
                counts["luw"] += len(analysis.luw)
    return counts
