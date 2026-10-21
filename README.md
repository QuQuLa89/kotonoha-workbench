# kotonoha-workbench

手元の日本語コーパスをMeCabとUniDicで短単位に解析し、長単位との包含関係をSQLiteに保存するCLIです。長単位の語彙素・品詞と、第N要素の短単位条件を組み合わせて検索できます。Phase 1のバージョンは `0.1.0` です。

## インストール

Python 3.10以上を使います。Windows PowerShellでは次のコマンドを実行してください。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m pre_commit install
```

macOS・Linuxでは仮想環境の有効化に `source .venv/bin/activate` を使います。MeCabと軽量辞書 `unidic-lite` は依存パッケージとして導入されます。

## 取り込み

```powershell
kotonoha ingest corpus.txt --db corpus.sqlite3 --no-comainu
kotonoha ingest interviews.csv --text-column 本文 --db corpus.sqlite3
kotonoha ingest interviews.tsv --text-column text --db corpus.sqlite3
```

`.txt` は句点・疑問符・感嘆符・改行で分割します。CSV・TSVはヘッダーを必須とし、本文セル1件を1文書・1文として扱います。本文中に句点や改行があっても行の単位を保ちます。空の本文は文書だけ保存します。本文列の省略時は `text`、`本文`、`テキスト`、`発話` の順で探し、該当しなければ先頭列を使います。ほかの列は行番号とともにメタデータへ保存します。

文字コードはUTF-8を優先し、失敗した場合はCP932を使います。UTF-8のBOMはデコード時に除きます。改行コードは保持します。不正な文字列を置換して取り込む処理はしません。再取り込みは追加保存です。1ファイルの取り込みに失敗した場合、そのファイルの追加データ全体をロールバックします。

## 検索と出力

```powershell
kotonoha search --db corpus.sqlite3 --luw-lemma 東京都現代美術館 --kwic
kotonoha search --db corpus.sqlite3 --luw-pos 名詞 --suw-pos 接頭辞 --position 1 --kwic
kotonoha search --db corpus.sqlite3 --luw-pos 動詞 --suw-pos 動詞 --suw-c-form 連用形 --position 1 --kwic
kotonoha search --db corpus.sqlite3 --suw-lemma 立ち上がる --position 1 --export-csv verbs.csv
kotonoha search --db corpus.sqlite3 --export-tsv all.tsv
```

語彙素は完全一致、品詞と活用形は階層単位の前方一致で検索します。例えば `名詞` は `名詞-普通名詞` にも一致します。`--suw-lemma`、`--suw-pos`、`--suw-c-form`、`--position` は同じ構成短単位に適用します。条件を省略すると全長単位を返します。件数は長単位の件数です。KWICは原文から前後40文字を切り出します。

CSV・TSVはUTF-8 BOM付きで出力し、長単位ごとに構成短単位を順序付きで1行ずつ書き出します。ファイル名は未使用の名前を指定してください。発話番号/文番号はDB内で一意な文ID、長単位IDはDB内のIDです。出力は引き継ぎ仕様のWeb茶まめ互換21列に合わせています。Web茶まめ本体とのファイル相互取り込みは未検証です。中納言の検索条件のうち、上記の長単位・短長クロス検索とKWICに対応しています。

## 長単位解析

ComainuがPATH上にある場合は公式の `plain2longout` コマンドを使います。`--comainu` でも実行ファイルを指定できます。Perlスクリプトを直接起動できない環境では、引数と標準入出力を転送する実行ラッパーを用意してください。Python APIの `Analyzer(comainu_command=["perl", "path/to/comainu.pl"])` でも指定できます。

Comainuが見つからない場合は規則による長単位化を使います。起動失敗・タイムアウト・出力不正・短単位境界の不一致があれば警告を出して規則へ切り替えます。実際に使った方式は各文書の `analysis_backends` に記録します。`--no-comainu` を指定すると常に規則を使います。

規則は解析用テキストの空白を越えず、次を結合します。除去したルビは結合を妨げません。

- 普通名詞・固有名詞・名詞的接尾辞の連続
- 接頭辞または形容詞語幹と後続する名詞群
- 連用形動詞と後続する動詞
- 動詞に続く助動詞・接尾辞

長単位品詞は先頭の実質語の大分類です。複合名詞の語彙素は表層形、動詞の語彙素は前項の表層形と末尾動詞の語彙素から作ります。助動詞と接尾辞は動詞語彙素の構成から除きます。これはPhase 1の近似規則で、Comainuの解析や国語研の長単位認定と一致する保証はありません。辞書が1短単位として出力した複合語を、独自に再分割することもありません。

Comainu実機との連携は未検証です。単体テストでは公式形式の出力例と模擬プロセスによって連携部分を検証します。

## データモデルと文字位置

| テーブル      | 内容                                                                             |
| ------------- | -------------------------------------------------------------------------------- |
| `documents`   | デコード後・ルビ除去前の本文、文字数、属性、ルビ情報、オフセットマップ、解析方式 |
| `sentences`   | 解析用の文、文書ID、文内番号、原文での開始・終了位置                             |
| `suw_tokens`  | UniDic短単位の表層・品詞4階層・活用・語彙素・読み・発音・語種・原文位置          |
| `luw_tokens`  | 長単位の表層・品詞・語彙素・原文位置                                             |
| `luw_members` | 長単位ID、短単位ID、1から始まる構成順序                                          |

`sentence_index`・`token_index`・`luw_index` は0から始まります。文字位置は各 `documents.original_text` 内のPython文字インデックスで、開始を含み終了を含みません。CSV・TSVではCSVファイル全体ではなく、各本文セルが原文です。CSVの引用符などの表形式の構文は文書本文に含めません。

青空文庫形式の `｜漢字《かんじ》`、`漢字《かんじ》` と、漢字直後にかなだけを置いた `漢字（かんじ）`・`漢字(かんじ)` を解析前に除去します。一般の括弧注記は残しますが、かなだけの注記とルビの区別はできません。退避情報には元の表記・読み・基底文字範囲を保存します。

トークンの開始・終了は対応する基底文字の最初と最後から求めます。したがってKWICのキーや文脈に原文のルビ・区切り記号が入ることがあります。解析表層と原文キーの違いを保ち、ルビを消した文字列から原文を復元する処理はしません。SQLiteの外部キー・一意制約と文をまたぐ包含関係の検査を有効にしています。

## 開発時の検証

```powershell
python -m pytest
python -m ruff format .
python -m ruff check --fix .
python -m ruff check .
python -m ruff format --check .
python -m pre_commit run --all-files
python -m build
```

## 参照資料

- [mecab-python3公式README](https://github.com/SamuraiT/mecab-python3)
- [UniDic Lite公式README](https://github.com/polm/unidic-lite)
- [UniDic公式FAQ](https://clrd.ninjal.ac.jp/unidic/faq.html)
- [Comainu公式READMEとplain2longout形式](https://github.com/skozawa/Comainu)

MIT License / Copyright (c) 2026 QuQuLa89
