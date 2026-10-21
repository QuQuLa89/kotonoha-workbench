import csv

import pytest

from kotonoha.preprocessor import (
    decode_source,
    load_documents,
    remove_ruby,
    split_sentences,
)


@pytest.mark.parametrize(
    "original,clean",
    [
        ("前｜漢字《かんじ》後", "前漢字後"),
        ("漢字《かんじ》です。", "漢字です。"),
        ("漢字（かんじ）と漢字(カンジ)", "漢字と漢字"),
        ("｜食べる《たべる》", "食べる"),
        ("漢字（注釈です）", "漢字（注釈です）"),
        ("😀\r\n東京  東京", "😀\r\n東京  東京"),
        ("", ""),
    ],
)
def test_ruby_and_character_map(original, clean):
    result = remove_ruby(original)
    assert result.text == clean
    assert len(result.offsets) == len(clean)
    assert "".join(original[i] for i in result.offsets) == clean
    assert list(result.offsets) == sorted(set(result.offsets))


def test_ruby_metadata_and_spans():
    original = "前｜漢字《かんじ》後"
    result = remove_ruby(original)
    assert result.original_span(1, 3) == (2, 4)
    assert result.rubies[0]["reading"] == "かんじ"
    assert (
        original[result.rubies[0]["start_char"] : result.rubies[0]["end_char"]]
        == "｜漢字《かんじ》"
    )
    with pytest.raises(ValueError):
        result.original_span(0, 0)


def test_split_preserves_crlf_offsets():
    original = "  一文。\r\n二文！次？\n\n終わり"
    sentences = split_sentences(remove_ruby(original))
    assert [s.text for s in sentences] == ["一文。", "二文！", "次？", "終わり"]
    assert all(original[s.start_char : s.end_char] == s.text for s in sentences)


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "cp932"])
def test_encoding_and_raw_line_endings(tmp_path, encoding):
    path = tmp_path / "sample.txt"
    original = "漢字\r\n次。"
    path.write_bytes(original.encode(encoding))
    document = load_documents(path)[0]
    assert document.original_text == original
    assert document.metadata["encoding"] == (
        "cp932" if encoding == "cp932" else "utf-8"
    )


def test_invalid_encoding_is_not_replaced():
    with pytest.raises(UnicodeDecodeError):
        decode_source(b"\x81")


@pytest.mark.parametrize("suffix,delimiter", [("csv", ","), ("tsv", "\t")])
def test_table_rows_metadata_and_quoted_newlines(tmp_path, suffix, delimiter):
    path = tmp_path / f"sample.{suffix}"
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, delimiter=delimiter)
        writer.writerow(["話者ID", "本文", "年代"])
        writer.writerow(["A", "漢字（かんじ）。\n次、です。", "2026"])
        writer.writerow(["B", "", "2025"])
    documents = load_documents(path)
    assert len(documents) == 2
    assert len(documents[0].sentences) == 1
    assert documents[0].sentences[0].text == "漢字。\n次、です。"
    assert documents[0].metadata["attributes"] == {"話者ID": "A", "年代": "2026"}
    assert documents[0].metadata["row_index"] == 1
    assert documents[1].sentences == ()


def test_explicit_text_column_and_first_column_fallback(tmp_path):
    path = tmp_path / "sample.csv"
    path.write_text("id,body\nA,内容\n", encoding="utf-8")
    assert load_documents(path)[0].original_text == "A"
    assert load_documents(path, text_column="body")[0].original_text == "内容"
    with pytest.raises(ValueError, match="テキスト列"):
        load_documents(path, text_column="missing")


@pytest.mark.parametrize(
    "content", ["", "text,text\nA,B", "text,id\nA", "text,id\nA,B,C", ",id\nA,B"]
)
def test_malformed_table_is_rejected(tmp_path, content):
    path = tmp_path / "bad.csv"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError):
        load_documents(path)


def test_unsupported_extension(tmp_path):
    with pytest.raises(ValueError, match="入力形式"):
        load_documents(tmp_path / "sample.json")
