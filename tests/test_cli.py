import csv
import os
import subprocess
import sys

import pytest

from kotonoha.cli import main


def test_ingest_search_and_exports(tmp_path, capsys):
    path = tmp_path / "corpus.txt"
    path.write_text("東京都現代美術館。安請け合い。立ち上がる。", encoding="utf-8")
    db = str(tmp_path / "corpus.sqlite3")
    assert main(["ingest", str(path), "--db", db, "--no-comainu"]) == 0
    assert "取り込み完了" in capsys.readouterr().out
    out = tmp_path / "out.csv"
    tsv = tmp_path / "out.tsv"
    assert (
        main(
            [
                "search",
                "--db",
                db,
                "--luw-lemma",
                "東京都現代美術館",
                "--kwic",
                "--export-csv",
                str(out),
                "--export-tsv",
                str(tsv),
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "検索結果: 1件" in output
    assert "東京都現代美術館" in output
    with out.open(encoding="utf-8-sig", newline="") as stream:
        assert len(list(csv.reader(stream))) == 6
    with tsv.open(encoding="utf-8-sig", newline="") as stream:
        assert len(list(csv.reader(stream, delimiter="\t"))) == 6


def test_text_column_cli_and_no_results(tmp_path, capsys):
    path = tmp_path / "input.tsv"
    path.write_text("id\tbody\nA\t東京都現代美術館\n", encoding="utf-8")
    db = str(tmp_path / "corpus.db")
    assert (
        main(["ingest", str(path), "--db", db, "--text-column", "body", "--no-comainu"])
        == 0
    )
    capsys.readouterr()
    assert main(["search", "--db", db, "--luw-lemma", "missing"]) == 0
    assert "検索結果: 0件" in capsys.readouterr().out


@pytest.mark.parametrize("command", ["ingest", "search"])
def test_missing_inputs_report_error(tmp_path, capsys, command):
    args = (
        ["ingest", str(tmp_path / "missing.txt")]
        if command == "ingest"
        else ["search", "--db", str(tmp_path / "missing.db")]
    )
    assert main(args) == 1
    assert "エラー:" in capsys.readouterr().err
    assert not (tmp_path / "missing.db").exists()


def test_invalid_position_rejected():
    with pytest.raises(SystemExit) as error:
        main(["search", "--position", "0"])
    assert error.value.code == 2


def test_module_entrypoint():
    result = subprocess.run(
        [sys.executable, "-m", "kotonoha.cli", "--version"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    assert result.stdout.strip() == "0.1.0"
