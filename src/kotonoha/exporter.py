"""引き継ぎ仕様の21列で短単位をCSV/TSVに出力します。"""

import csv
import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import TextIO

from kotonoha.search import SearchHit, search

HEADERS = (
    "発話番号/文番号",
    "長単位ID",
    "長単位表層",
    "長単位品詞",
    "長単位語彙素",
    "短単位順序",
    "表層形",
    "品詞",
    "品詞細分類1",
    "品詞細分類2",
    "品詞細分類3",
    "活用型",
    "活用形",
    "書字形出現形",
    "発音",
    "語彙素",
    "語彙素読み",
    "語種",
    "前文脈",
    "キー",
    "後文脈",
)


def write_results(
    connection: sqlite3.Connection,
    stream: TextIO,
    hits: Iterable[SearchHit] | None = None,
    *,
    delimiter: str = ",",
) -> int:
    if delimiter not in {",", "\t"}:
        raise ValueError("区切り文字はカンマまたはタブを指定してください。")
    writer = csv.writer(stream, delimiter=delimiter, lineterminator="\n")
    writer.writerow(HEADERS)
    count = 0
    for hit in search(connection) if hits is None else hits:
        rows = connection.execute(
            """SELECT m.position, s.* FROM luw_members m
                                    JOIN suw_tokens s ON s.id=m.suw_id
                                    WHERE m.luw_id=? ORDER BY m.position""",
            (hit.luw_id,),
        )
        for row in rows:
            writer.writerow(
                [
                    hit.sentence_id,
                    hit.luw_id,
                    hit.surface,
                    hit.pos,
                    hit.lemma,
                    row["position"],
                    *[
                        row[k]
                        for k in (
                            "surface",
                            "pos1",
                            "pos2",
                            "pos3",
                            "pos4",
                            "c_type",
                            "c_form",
                            "orth_token",
                            "pronunciation",
                            "lemma",
                            "lemma_reading",
                            "goshu",
                        )
                    ],
                    hit.left_context,
                    hit.key,
                    hit.right_context,
                ]
            )
            count += 1
    return count


def export_results(
    connection: sqlite3.Connection,
    path: str | Path,
    hits: Iterable[SearchHit] | None = None,
    *,
    delimiter: str = ",",
) -> int:
    # 既存ファイルは上書きせず、出力先の変更を求めます。
    with Path(path).open("x", encoding="utf-8-sig", newline="") as stream:
        return write_results(connection, stream, hits, delimiter=delimiter)
