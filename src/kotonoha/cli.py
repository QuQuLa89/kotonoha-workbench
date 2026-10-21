"""取り込みと検索のコマンドラインインターフェース。"""

import argparse
import csv
import sqlite3
import sys
from contextlib import closing

from kotonoha import __version__
from kotonoha.analyzer import Analyzer
from kotonoha.db import connect, ingest_documents, initialize
from kotonoha.exporter import export_results
from kotonoha.preprocessor import load_documents
from kotonoha.search import search


def _positive(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("1以上の整数を指定してください。")
    return number


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="日本語コーパスの短単位・長単位検索")
    root.add_argument("--version", action="version", version=__version__)
    commands = root.add_subparsers(dest="command", required=True)
    ingest = commands.add_parser("ingest", help="コーパスを取り込みます。")
    ingest.add_argument("file_path")
    ingest.add_argument("--db", default="kotonoha.sqlite3")
    ingest.add_argument("--text-column", help="CSV/TSVの本文列名")
    ingest.add_argument(
        "--no-comainu", action="store_true", help="規則による長単位化を使います。"
    )
    ingest.add_argument("--comainu", help="Comainu実行ファイルのパス")
    query = commands.add_parser("search", help="長単位と短単位の条件で検索します。")
    query.add_argument("--db", default="kotonoha.sqlite3")
    for name in ("luw-lemma", "luw-pos", "suw-lemma", "suw-pos", "suw-c-form"):
        query.add_argument(f"--{name}")
    query.add_argument("--position", type=_positive)
    query.add_argument("--kwic", action="store_true")
    query.add_argument("--export-csv")
    query.add_argument("--export-tsv")
    return root


def main(argv: list[str] | None = None) -> int:
    root = parser()
    args = root.parse_args(argv)
    try:
        if args.command == "ingest":
            documents = load_documents(args.file_path, text_column=args.text_column)
            analyzer = Analyzer(
                comainu_command=[args.comainu] if args.comainu else None,
                use_comainu=not args.no_comainu,
            )
            with closing(connect(args.db)) as connection:
                initialize(connection)
                counts = ingest_documents(connection, documents, analyzer)
            print(
                f"取り込み完了: {counts['documents']}文書、{counts['sentences']}文、"
                f"短単位{counts['suw']}件、長単位{counts['luw']}件"
            )
        else:
            with closing(connect(args.db, readonly=True)) as connection:
                hits = search(
                    connection,
                    **{
                        name: getattr(args, name)
                        for name in (
                            "luw_lemma",
                            "luw_pos",
                            "suw_lemma",
                            "suw_pos",
                            "suw_c_form",
                            "position",
                        )
                    },
                )
                print(f"検索結果: {len(hits)}件")
                if args.kwic:
                    writer = csv.writer(sys.stdout, delimiter="\t", lineterminator="\n")
                    for hit in hits:
                        writer.writerow([hit.left_context, hit.key, hit.right_context])
                for path, delimiter in (
                    (args.export_csv, ","),
                    (args.export_tsv, "\t"),
                ):
                    if path:
                        count = export_results(
                            connection, path, hits, delimiter=delimiter
                        )
                        print(f"出力完了: {count}行 ({path})")
    except (OSError, ValueError, sqlite3.Error, csv.Error, RuntimeError) as error:
        print(f"エラー: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
