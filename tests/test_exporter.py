import csv
import io

import pytest

from kotonoha.exporter import export_results, write_results
from kotonoha.search import search

EXPECTED = (
    "発話番号/文番号,長単位ID,長単位表層,長単位品詞,長単位語彙素,短単位順序,"
    "表層形,品詞,品詞細分類1,品詞細分類2,品詞細分類3,活用型,活用形,"
    "書字形出現形,発音,語彙素,語彙素読み,語種,前文脈,キー,後文脈"
).split(",")


@pytest.mark.parametrize("delimiter", [",", "\t"])
def test_exact_header_and_ordered_members(corpus, delimiter):
    stream = io.StringIO(newline="")
    assert (
        write_results(
            corpus,
            stream,
            search(corpus, luw_lemma="東京都現代美術館"),
            delimiter=delimiter,
        )
        == 5
    )
    rows = list(csv.reader(io.StringIO(stream.getvalue()), delimiter=delimiter))
    assert rows[0] == EXPECTED
    assert all(len(row) == 21 for row in rows)
    assert [row[5] for row in rows[1:]] == ["1", "2", "3", "4", "5"]
    assert [row[6] for row in rows[1:]] == ["東京", "都", "現代", "美術", "館"]
    assert rows[1][19] == "東京都現代美術館"
    assert rows[1][13:18] == ["東京", "トーキョー", "トウキョウ", "トウキョウ", "固"]


def test_all_corpus_bom_and_existing_file_protection(corpus, tmp_path):
    path = tmp_path / "results.csv"
    count = export_results(corpus, path)
    assert path.read_bytes().startswith(b"\xef\xbb\xbf")
    assert count == corpus.execute("SELECT count(*) FROM suw_tokens").fetchone()[0]
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        export_results(corpus, path)
    assert path.read_bytes() == before


def test_empty_results_have_header_only(corpus):
    stream = io.StringIO()
    assert write_results(corpus, stream, []) == 0
    assert list(csv.reader(io.StringIO(stream.getvalue()))) == [EXPECTED]


def test_csv_quoting_roundtrip(corpus):
    from dataclasses import replace

    hit = replace(search(corpus)[0], left_context='前,"引用"\n次\t')
    stream = io.StringIO(newline="")
    write_results(corpus, stream, [hit])
    rows = list(csv.reader(io.StringIO(stream.getvalue(), newline="")))
    assert rows[1][18] == hit.left_context


def test_invalid_delimiter(corpus):
    with pytest.raises(ValueError):
        write_results(corpus, io.StringIO(), delimiter="|")
