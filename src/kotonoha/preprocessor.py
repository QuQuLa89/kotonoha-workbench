"""原文を保持し、解析文字ごとの原文位置を追跡します。"""

import csv
import io
import re
from dataclasses import dataclass, field
from pathlib import Path

RUBY = re.compile(
    r"｜(?P<explicit>[^《\r\n]+)《(?P<explicit_read>[^》\r\n]+)》"
    r"|(?P<aozora>[一-龯々〆ヶ]+)《(?P<aozora_read>[^》\r\n]+)》"
    r"|(?P<paren>[一-龯々〆ヶ]+)[（(](?P<paren_read>[ぁ-ゖァ-ヺー・]+)[）)]"
)


@dataclass(frozen=True)
class PreparedText:
    text: str
    offsets: tuple[int, ...]
    rubies: tuple[dict, ...]

    def original_span(self, start: int, end: int) -> tuple[int, int]:
        if not 0 <= start < end <= len(self.offsets):
            raise ValueError("解析文字範囲が不正です。")
        return self.offsets[start], self.offsets[end - 1] + 1


@dataclass(frozen=True)
class Sentence:
    text: str
    offsets: tuple[int, ...]

    @property
    def start_char(self) -> int:
        return self.offsets[0]

    @property
    def end_char(self) -> int:
        return self.offsets[-1] + 1


@dataclass(frozen=True)
class Document:
    filename: str
    source_type: str
    original_text: str
    sentences: tuple[Sentence, ...]
    metadata: dict = field(default_factory=dict)


def remove_ruby(text: str) -> PreparedText:
    chars: list[str] = []
    offsets: list[int] = []
    rubies = []
    cursor = 0
    for match in RUBY.finditer(text):
        chars.extend(text[cursor : match.start()])
        offsets.extend(range(cursor, match.start()))
        kind = next(k for k in ("explicit", "aozora", "paren") if match[k])
        base_start, base_end = match.span(kind)
        chars.extend(match[kind])
        offsets.extend(range(base_start, base_end))
        rubies.append(
            {
                "start_char": match.start(),
                "end_char": match.end(),
                "base_start": base_start,
                "base_end": base_end,
                "base": match[kind],
                "reading": match[f"{kind}_read"],
                "notation": text[match.start() : match.end()],
            }
        )
        cursor = match.end()
    chars.extend(text[cursor:])
    offsets.extend(range(cursor, len(text)))
    return PreparedText("".join(chars), tuple(offsets), tuple(rubies))


def split_sentences(
    prepared: PreparedText, *, split: bool = True
) -> tuple[Sentence, ...]:
    spans = (
        [
            (m.start(), m.end())
            for m in re.finditer(
                r"[^。！？!?\r\n]+[。！？!?]?|[。！？!?]", prepared.text
            )
        ]
        if split
        else [(0, len(prepared.text))]
    )
    sentences = []
    for start, end in spans:
        while start < end and prepared.text[start].isspace():
            start += 1
        while end > start and prepared.text[end - 1].isspace():
            end -= 1
        if start < end:
            sentences.append(
                Sentence(prepared.text[start:end], prepared.offsets[start:end])
            )
    return tuple(sentences)


def decode_source(data: bytes) -> tuple[str, str]:
    try:
        return data.decode("utf-8-sig"), "utf-8"
    except UnicodeDecodeError:
        return data.decode("cp932"), "cp932"


def load_documents(
    path: str | Path, *, text_column: str | None = None
) -> list[Document]:
    path = Path(path)
    source_type = path.suffix.lower().lstrip(".")
    if source_type not in {"txt", "csv", "tsv"}:
        raise ValueError("入力形式は .txt、.csv、.tsv に対応しています。")
    text, encoding = decode_source(path.read_bytes())

    def document(original: str, metadata: dict, *, split: bool) -> Document:
        prepared = remove_ruby(original)
        return Document(
            path.name,
            source_type,
            original,
            split_sentences(prepared, split=split),
            {
                **metadata,
                "encoding": encoding,
                "rubies": list(prepared.rubies),
            },
        )

    if source_type == "txt":
        return [document(text, {}, split=True)]
    reader = csv.DictReader(
        io.StringIO(text, newline=""),
        delimiter="," if source_type == "csv" else "\t",
        strict=True,
    )
    fields = reader.fieldnames
    if not fields or any(not f for f in fields) or len(set(fields)) != len(fields):
        raise ValueError("重複のない列名を持つヘッダーが必要です。")
    if text_column is None:
        text_column = next(
            (f for f in ("text", "本文", "テキスト", "発話") if f in fields), fields[0]
        )
    if text_column not in fields:
        raise ValueError(f"テキスト列が見つかりません: {text_column}")
    result = []
    for row_index, row in enumerate(reader, 1):
        if None in row or any(value is None for value in row.values()):
            raise ValueError(f"行 {row_index} の列数がヘッダーと一致しません。")
        result.append(
            document(
                row[text_column],
                {
                    "row_index": row_index,
                    "text_column": text_column,
                    "attributes": {k: v for k, v in row.items() if k != text_column},
                },
                split=False,
            )
        )
    return result
