"""UniDic短単位と、Comainuまたは規則による長単位解析。"""

import csv
import io
import shutil
import subprocess
import warnings
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from kotonoha.preprocessor import Sentence


@dataclass(frozen=True)
class ShortUnit:
    token_index: int
    surface: str
    pos1: str
    pos2: str
    pos3: str
    pos4: str
    c_type: str
    c_form: str
    lemma: str
    lemma_reading: str
    pronunciation: str
    orth_token: str
    goshu: str
    start_char: int
    end_char: int


@dataclass(frozen=True)
class LongUnit:
    luw_index: int
    surface: str
    pos: str
    lemma: str
    start_char: int
    end_char: int
    members: tuple[int, ...]  # ShortUnit.token_index。DB保存時にIDへ変換します。


@dataclass(frozen=True)
class Analysis:
    suw: tuple[ShortUnit, ...]
    luw: tuple[LongUnit, ...]
    backend: str


def _noun(token: ShortUnit) -> bool:
    return (token.pos1 == "名詞" and token.pos2 in {"普通名詞", "固有名詞"}) or (
        token.pos1 == "接尾辞" and token.pos2 == "名詞的"
    )


def _prefix(token: ShortUnit) -> bool:
    return token.pos1 == "接頭辞" or (
        token.pos1 == "形容詞" and token.c_form.startswith("語幹")
    )


def _long_unit(
    index: int,
    group: Sequence[ShortUnit],
    *,
    pos: str | None = None,
    lemma: str | None = None,
) -> LongUnit:
    surface = "".join(t.surface for t in group)
    head = next((t for t in group if not _prefix(t)), group[0])
    # 活用する末尾の語彙素を用い、前項は出現形を保持します。
    if lemma is None:
        lexical = [t for t in group if t.pos1 not in {"助動詞", "接尾辞"}]
        if head.pos1 == "動詞" and lexical:
            last = lexical[-1]
            lemma = "".join(t.surface for t in lexical[:-1]) + last.lemma
        elif len(group) == 1:
            lemma = group[0].lemma
        else:
            lemma = surface
    return LongUnit(
        index,
        surface,
        pos or head.pos1,
        lemma,
        group[0].start_char,
        group[-1].end_char,
        tuple(t.token_index for t in group),
    )


def fallback_long_units(
    tokens: Sequence[ShortUnit], *, sentence: Sentence | None = None
) -> tuple[LongUnit, ...]:
    clean_positions = (
        {original: index for index, original in enumerate(sentence.offsets)}
        if sentence is not None
        else None
    )
    groups: list[list[ShortUnit]] = []
    for token in tokens:
        if not groups:
            groups.append([token])
            continue
        group = groups[-1]
        previous = group[-1]
        head = group[0]
        adjacent = previous.end_char == token.start_char
        if clean_positions is not None:
            adjacent = (
                clean_positions[previous.end_char - 1] + 1
                == clean_positions[token.start_char]
            )
        noun_join = _noun(token) and (
            all(_noun(t) for t in group)
            or (_prefix(head) and all(_noun(t) for t in group[1:]))
        )
        verb_join = head.pos1 == "動詞" and (
            (
                token.pos1 == "動詞"
                and previous.pos1 == "動詞"
                and previous.c_form.startswith("連用形")
            )
            or token.pos1 in {"助動詞", "接尾辞"}
        )
        if adjacent and (noun_join or verb_join):
            group.append(token)
        else:
            groups.append([token])
    return tuple(_long_unit(i, group) for i, group in enumerate(groups))


def parse_comainu(output: str, tokens: Sequence[ShortUnit]) -> tuple[LongUnit, ...]:
    """公式 plain2longout の14列を読み、短単位の完全一致を検証します。"""
    rows = [line.split("\t") for line in output.splitlines() if line and line != "EOS"]
    if len(rows) != len(tokens) or any(len(row) != 14 for row in rows):
        raise ValueError("Comainu出力の列数または短単位数が一致しません。")
    result = []
    group: list[ShortUnit] = []
    pos = lemma = ""
    for row, token in zip(rows, tokens, strict=True):
        if row[1] != token.surface:
            raise ValueError("ComainuとMeCabの短単位境界が一致しません。")
        if row[9] != "*":
            if group:
                result.append(_long_unit(len(result), group, pos=pos, lemma=lemma))
            group = []
            pos, lemma = row[9], row[12]
        elif not group:
            raise ValueError("Comainuの先頭長単位が欠けています。")
        group.append(token)
    if group:
        result.append(_long_unit(len(result), group, pos=pos, lemma=lemma))
    return tuple(result)


class Analyzer:
    def __init__(
        self,
        *,
        comainu_command: Sequence[str] | None = None,
        use_comainu: bool = True,
        timeout: float = 60,
    ):
        import MeCab
        import unidic_lite

        dicdir = Path(unidic_lite.DICDIR).as_posix()
        self.tagger = MeCab.Tagger(f'-r "{dicdir}/mecabrc" -d "{dicdir}"')
        self.timeout = timeout
        discovered = (
            shutil.which("comainu") or shutil.which("comainu.pl")
            if use_comainu
            else None
        )
        self.comainu_command = (
            tuple(comainu_command or ([discovered] if discovered else []))
            if use_comainu
            else ()
        )

    def short_units(self, sentence: Sentence) -> tuple[ShortUnit, ...]:
        result = []
        cursor = 0
        node = self.tagger.parseToNode(sentence.text)
        while node:
            if node.surface:
                surface = node.surface
                start = sentence.text.find(surface, cursor)
                if start < 0 or sentence.text[cursor:start].strip():
                    raise ValueError("MeCabの解析結果を原文位置に対応付けられません。")
                end = start + len(surface)
                fields = next(csv.reader(io.StringIO(node.feature)))
                fields += ["*"] * max(0, 13 - len(fields))
                values = ["" if f == "*" else f for f in fields]
                result.append(
                    ShortUnit(
                        len(result),
                        surface,
                        *values[:6],
                        values[7] or surface,
                        values[6],
                        values[9],
                        values[8] or surface,
                        values[12],
                        sentence.offsets[start],
                        sentence.offsets[end - 1] + 1,
                    )
                )
                cursor = end
            node = node.next
        if sentence.text[cursor:].strip():
            raise ValueError("解析されていない文字が残っています。")
        return tuple(result)

    def analyze(self, sentence: Sentence) -> Analysis:
        suw = self.short_units(sentence)
        if self.comainu_command and suw:
            try:
                completed = subprocess.run(
                    [*self.comainu_command, "plain2longout"],
                    input=(sentence.text + "\n").encode("utf-8"),
                    capture_output=True,
                    timeout=self.timeout,
                    check=True,
                    shell=False,
                )
                return Analysis(
                    suw, parse_comainu(completed.stdout.decode("utf-8"), suw), "comainu"
                )
            except (OSError, subprocess.SubprocessError, ValueError) as error:
                warnings.warn(
                    "Comainu連携に失敗したため規則に切り替えます: "
                    f"{type(error).__name__}",
                    RuntimeWarning,
                    stacklevel=2,
                )
        return Analysis(suw, fallback_long_units(suw, sentence=sentence), "fallback")
