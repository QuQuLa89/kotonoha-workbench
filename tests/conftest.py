import pytest

from kotonoha.analyzer import Analyzer
from kotonoha.db import connect, ingest_documents, initialize
from kotonoha.preprocessor import load_documents


@pytest.fixture(scope="session")
def analyzer():
    return Analyzer(use_comainu=False)


@pytest.fixture
def connection():
    connection = connect(":memory:")
    initialize(connection)
    yield connection
    connection.close()


@pytest.fixture
def corpus(connection, analyzer, tmp_path):
    path = tmp_path / "corpus.txt"
    path.write_text(
        "東京都現代美術館に行きました。\n安請け合いをする。\n立ち上がりました。",
        encoding="utf-8",
    )
    ingest_documents(connection, load_documents(path), analyzer)
    return connection
