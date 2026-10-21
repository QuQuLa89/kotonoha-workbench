import subprocess
import sys
from dataclasses import replace

import pytest

from kotonoha.analyzer import Analyzer, fallback_long_units, parse_comainu
from kotonoha.preprocessor import remove_ruby, split_sentences


def sentence(text):
    return split_sentences(remove_ruby(text), split=False)[0]


def test_compound_noun_features_and_members(analyzer):
    analysis = analyzer.analyze(sentence("東京都現代美術館に行きました。"))
    assert [t.surface for t in analysis.suw[:5]] == ["東京", "都", "現代", "美術", "館"]
    assert analysis.luw[0].surface == "東京都現代美術館"
    assert analysis.luw[0].members == (0, 1, 2, 3, 4)
    assert analysis.luw[0].pos == "名詞"
    tokyo = analysis.suw[0]
    assert (tokyo.pos1, tokyo.pos2, tokyo.pos3, tokyo.pos4) == (
        "名詞",
        "固有名詞",
        "地名",
        "一般",
    )
    assert tokyo.lemma_reading == "トウキョウ"
    assert tokyo.pronunciation == "トーキョー"
    assert tokyo.orth_token == "東京"
    assert tokyo.goshu == "固"
    assert analysis.luw[2].lemma == "行く"
    assert analysis.luw[2].surface == "行きました"
    assert sorted(m for unit in analysis.luw for m in unit.members) == list(
        range(len(analysis.suw))
    )


def test_adjective_stem_noun_and_prefix_rule(analyzer):
    analysis = analyzer.analyze(sentence("安請け合い"))
    assert [t.surface for t in analysis.suw] == ["安", "請け合い"]
    assert analysis.suw[0].pos1 == "形容詞"
    assert analysis.suw[0].c_form.startswith("語幹")
    assert (analysis.luw[0].surface, analysis.luw[0].pos, analysis.luw[0].members) == (
        "安請け合い",
        "名詞",
        (0, 1),
    )
    prefix = replace(analysis.suw[0], pos1="接頭辞", c_form="")
    assert fallback_long_units((prefix, analysis.suw[1]))[0].members == (0, 1)


def test_dictionary_compound_verb_is_not_resplit(analyzer):
    analysis = analyzer.analyze(sentence("立ち上がりました"))
    assert [t.surface for t in analysis.suw] == ["立ち上がり", "まし", "た"]
    assert analysis.luw[0].lemma == "立ち上がる"
    assert analysis.luw[0].members == (0, 1, 2)


def test_split_compound_verb_rule(analyzer):
    first = analyzer.short_units(sentence("立ち"))[0]
    first = replace(
        first,
        surface="立ち",
        pos1="動詞",
        lemma="立つ",
        c_form="連用形-一般",
        start_char=0,
        end_char=2,
    )
    second = replace(
        analyzer.short_units(sentence("上がる"))[0],
        token_index=1,
        start_char=2,
        end_char=5,
    )
    result = fallback_long_units((first, second))
    assert len(result) == 1
    assert result[0].surface == result[0].lemma == "立ち上がる"
    assert result[0].members == (0, 1)
    assert len(fallback_long_units((replace(first, c_form="終止形-一般"), second))) == 2


@pytest.mark.parametrize(
    "text",
    ["東京 東京", "東京\t都", "東京《とうきょう》都", "😀東京\u3000東京", "ABC  ABC"],
)
def test_offsets_repeated_unicode_and_whitespace(analyzer, text):
    analysis = analyzer.analyze(sentence(text))
    for token in analysis.suw:
        assert text[token.start_char : token.end_char] == token.surface
    for long in analysis.luw:
        assert remove_ruby(text[long.start_char : long.end_char]).text == long.surface


def comainu_output(tokens):
    # 公式READMEのplain2longoutと同じ14列です。
    return (
        "\n".join(
            "\t".join(
                [
                    "B" if i == 0 else "",
                    t.surface,
                    t.pronunciation,
                    t.lemma_reading,
                    t.lemma,
                    t.pos1,
                    t.c_type,
                    t.c_form,
                    t.goshu,
                    "名詞-普通名詞-一般" if i == 0 else "*",
                    "*",
                    "*",
                    "東京都現代美術館" if i == 0 else "*",
                    "東京都現代美術館" if i == 0 else "*",
                ]
            )
            for i, t in enumerate(tokens)
        )
        + "\nEOS\n"
    )


def test_comainu_parser_and_subprocess(analyzer, tmp_path):
    text = "東京都現代美術館"
    tokens = analyzer.short_units(sentence(text))
    output = comainu_output(tokens)
    assert parse_comainu(output, tokens)[0].members == (0, 1, 2, 3, 4)
    script = tmp_path / "comainu_stub.py"
    script.write_text(
        "import sys\nassert sys.argv[1] == 'plain2longout'\n"
        "assert sys.stdin.buffer.read().decode('utf-8') == " + repr(text + "\n") + "\n"
        "sys.stdout.buffer.write(" + repr(output.encode("utf-8")) + ")\n",
        encoding="utf-8",
    )
    external = Analyzer(comainu_command=[sys.executable, str(script)])
    result = external.analyze(sentence(text))
    assert result.backend == "comainu"
    assert result.luw[0].pos == "名詞-普通名詞-一般"


@pytest.mark.parametrize(
    "kind", ["unavailable", "nonzero", "timeout", "malformed", "mismatch"]
)
def test_comainu_failure_falls_back(analyzer, monkeypatch, kind):
    external = Analyzer(comainu_command=["missing-comainu"])

    def run(*args, **kwargs):
        if kind == "unavailable":
            raise FileNotFoundError()
        if kind == "nonzero":
            raise subprocess.CalledProcessError(1, args[0])
        if kind == "timeout":
            raise subprocess.TimeoutExpired(args[0], 1)
        tokens = analyzer.short_units(sentence("東京都現代美術館"))
        output = (
            comainu_output(tokens).replace("東京", "京都", 1)
            if kind == "mismatch"
            else "bad"
        )
        return subprocess.CompletedProcess(args[0], 0, stdout=output.encode("utf-8"))

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.warns(RuntimeWarning, match="規則に切り替え"):
        result = external.analyze(sentence("東京都現代美術館"))
    assert result.backend == "fallback"
    assert result.luw[0].surface == "東京都現代美術館"


def test_comainu_auto_detection(monkeypatch):
    monkeypatch.setattr(
        "shutil.which", lambda name: "comainu" if name == "comainu" else None
    )
    assert Analyzer().comainu_command == ("comainu",)
    assert Analyzer(use_comainu=False).comainu_command == ()
