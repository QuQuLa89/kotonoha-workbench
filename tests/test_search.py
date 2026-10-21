import pytest

from kotonoha.db import ingest_documents
from kotonoha.preprocessor import load_documents
from kotonoha.search import search


def test_lemma_and_pos_queries(corpus):
    hits = search(corpus, luw_lemma="東京都現代美術館", luw_pos="名詞")
    assert len(hits) == 1
    assert hits[0].key == "東京都現代美術館"
    assert (
        search(corpus, luw_lemma="立ち上がる", luw_pos="動詞")[0].key
        == "立ち上がりました"
    )
    assert search(corpus, luw_lemma="missing") == []


def test_cross_conditions_apply_to_same_member(corpus):
    hits = search(
        corpus, luw_pos="名詞", suw_pos="形容詞", suw_c_form="語幹", position=1
    )
    assert [h.surface for h in hits] == ["安請け合い"]
    assert [
        h.surface
        for h in search(
            corpus, luw_pos="動詞", suw_pos="動詞", suw_c_form="連用形", position=1
        )
    ] == ["行きました", "立ち上がりました"]
    assert search(corpus, luw_lemma="東京都現代美術館", suw_lemma="現代", position=3)
    assert not search(
        corpus, luw_lemma="東京都現代美術館", suw_lemma="現代", position=1
    )
    assert not search(
        corpus, luw_lemma="東京都現代美術館", suw_lemma="現代", suw_pos="接尾辞"
    )
    assert search(
        corpus, luw_lemma="東京都現代美術館", suw_pos="名詞-固有名詞-地名", position=1
    )
    assert not search(corpus, luw_pos="名")
    assert not search(corpus, position=99)


def test_queries_treat_sql_and_wildcards_literally(corpus):
    assert not search(corpus, luw_lemma="' OR 1=1 --")
    assert not search(corpus, luw_pos="%")
    assert not search(corpus, suw_pos="_")
    assert search(corpus)


def test_kwic_exactly_40_original_characters(connection, analyzer, tmp_path):
    path = tmp_path / "context.txt"
    original = "あ" * 45 + "。\n東京都現代美術館に行く。" + "い" * 45
    path.write_bytes(original.encode("utf-8"))
    ingest_documents(connection, load_documents(path), analyzer)
    hit = search(connection, luw_lemma="東京都現代美術館")[0]
    start = original.index("東京")
    end = start + len(hit.key)
    assert hit.left_context == original[start - 40 : start]
    assert hit.right_context == original[end : end + 40]
    assert len(hit.left_context) == len(hit.right_context) == 40
    assert (
        search(connection, luw_lemma="東京都現代美術館", context_width=0)[
            0
        ].left_context
        == ""
    )


def test_kwic_ruby_uses_original_offsets(connection, analyzer, tmp_path):
    path = tmp_path / "ruby.txt"
    original = "😀前。｜東京《とうきょう》都現代美術館。後"
    path.write_text(original, encoding="utf-8")
    ingest_documents(connection, load_documents(path), analyzer)
    hit = search(connection, luw_lemma="東京都現代美術館")[0]
    assert hit.key == original[hit.start_char : hit.end_char]
    assert hit.left_context == original[: hit.start_char]
    assert "《とうきょう》" in hit.key


@pytest.mark.parametrize(
    "kwargs", [{"position": 0}, {"position": -1}, {"context_width": -1}]
)
def test_invalid_query_parameters(connection, kwargs):
    with pytest.raises(ValueError):
        search(connection, **kwargs)
