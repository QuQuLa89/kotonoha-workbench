"""長単位条件と同一短単位へのクロス条件、および原文KWIC。"""

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class SearchHit:
    luw_id: int
    sentence_id: int
    document_id: int
    filename: str
    surface: str
    pos: str
    lemma: str
    start_char: int
    end_char: int
    left_context: str
    key: str
    right_context: str


def _pos_condition(column: str, value: str, params: list) -> str:
    # 階層名は完全一致または「-」で区切られた子分類に一致させます。
    params.extend([value, value + "-"])
    return f"({column} = ? OR substr({column}, 1, {len(value) + 1}) = ?)"


def search(
    connection: sqlite3.Connection,
    *,
    luw_lemma: str | None = None,
    luw_pos: str | None = None,
    suw_lemma: str | None = None,
    suw_pos: str | None = None,
    suw_c_form: str | None = None,
    position: int | None = None,
    context_width: int = 40,
) -> list[SearchHit]:
    if position is not None and position < 1:
        raise ValueError("position は1以上で指定してください。")
    if context_width < 0:
        raise ValueError("文脈幅は0以上で指定してください。")
    conditions = []
    params: list = []
    if luw_lemma is not None:
        conditions.append("l.lemma = ?")
        params.append(luw_lemma)
    if luw_pos is not None:
        conditions.append(_pos_condition("l.pos", luw_pos, params))
    member_conditions = ["m.luw_id = l.id"]
    if position is not None:
        member_conditions.append("m.position = ?")
        params.append(position)
    if suw_lemma is not None:
        member_conditions.append("s.lemma = ?")
        params.append(suw_lemma)
    if suw_pos is not None:
        pos_column = "(s.pos1 || '-' || s.pos2 || '-' || s.pos3 || '-' || s.pos4)"
        member_conditions.append(_pos_condition(pos_column, suw_pos, params))
    if suw_c_form is not None:
        member_conditions.append(_pos_condition("s.c_form", suw_c_form, params))
    if any(v is not None for v in (position, suw_lemma, suw_pos, suw_c_form)):
        conditions.append(
            "EXISTS (SELECT 1 FROM luw_members m "
            "JOIN suw_tokens s ON s.id=m.suw_id WHERE "
            + " AND ".join(member_conditions)
            + ")"
        )
    sql = """SELECT l.*, d.id AS document_id, d.filename, d.original_text
             FROM luw_tokens l JOIN sentences t ON t.id=l.sentence_id
             JOIN documents d ON d.id=t.document_id"""
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY d.id, t.sentence_index, l.luw_index"
    hits = []
    for row in connection.execute(sql, params):
        start, end, original = row["start_char"], row["end_char"], row["original_text"]
        hits.append(
            SearchHit(
                row["id"],
                row["sentence_id"],
                row["document_id"],
                row["filename"],
                row["surface"],
                row["pos"],
                row["lemma"],
                start,
                end,
                original[max(0, start - context_width) : start],
                original[start:end],
                original[end : end + context_width],
            )
        )
    return hits
