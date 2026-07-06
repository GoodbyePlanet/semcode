from __future__ import annotations

import logging
from unittest.mock import AsyncMock, patch

import server.indexer.pipeline as pipeline_module
from server.config import ServiceConfig
from server.indexer.github_source import GitHubFile
from server.indexer.pipeline import (
    IndexPipeline,
    _build_bm25_text,
    _build_embedding_text,
)
from server.parser.base import CodeSymbol, ParseError

_TRUNCATION_MARKER = "// ... (truncated)"


class _StubEmbedder:
    dimensions = 1

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [[0.0]] * len(texts)


def _make_pipeline(store) -> IndexPipeline:
    pipeline = IndexPipeline.__new__(IndexPipeline)
    pipeline._store = store
    pipeline._embedder = _StubEmbedder()
    pipeline._sparse_embedder = _StubEmbedder()
    return pipeline


def _sym_with_source(source: str, docstring: str = "") -> CodeSymbol:
    return CodeSymbol(
        name="fn",
        symbol_type="function",
        language="python",
        source=source,
        file_path="svc/mod.py",
        start_line=1,
        end_line=1,
        docstring=docstring,
    )


def _sym(docstring: str) -> CodeSymbol:
    return CodeSymbol(
        name="fn",
        symbol_type="function",
        language="python",
        source="def fn(): pass",
        file_path="svc/mod.py",
        start_line=1,
        end_line=1,
        docstring=docstring,
    )


def test_python_triple_double_quote_stripped() -> None:
    text = _build_embedding_text(_sym('"""Hello world"""'), "svc")
    assert "Hello world" in text
    assert '"""' not in text


def test_python_triple_single_quote_stripped() -> None:
    text = _build_embedding_text(_sym("'''Important note'''"), "svc")
    assert "Important note" in text
    assert "'''" not in text


def test_jsdoc_delimiters_stripped() -> None:
    text = _build_embedding_text(_sym("/** Does something */"), "svc")
    assert "Does something" in text
    assert "/**" not in text
    assert "*/" not in text


def test_docstring_content_not_mangled() -> None:
    text = _build_embedding_text(_sym('"""important content"""'), "svc")
    assert "important content" in text


def test_bm25_text_contains_signature_and_source() -> None:
    sym = CodeSymbol(
        name="placeOrder",
        symbol_type="method",
        language="java",
        source="void placeOrder(PlaceOrderRequest req) {}",
        file_path="svc/Order.java",
        start_line=10,
        end_line=12,
        signature="void placeOrder(PlaceOrderRequest req)",
        docstring="Places an order.",
    )
    text = _build_bm25_text(sym)
    assert "void placeOrder(PlaceOrderRequest req)" in text
    assert "Places an order." in text
    assert "void placeOrder(PlaceOrderRequest req) {}" in text


def test_bm25_text_excludes_preamble() -> None:
    sym = CodeSymbol(
        name="placeOrder",
        symbol_type="method",
        language="java",
        source="void placeOrder() {}",
        file_path="svc/Order.java",
        start_line=1,
        end_line=3,
    )
    bm25 = _build_bm25_text(sym)
    dense = _build_embedding_text(sym, "orders-service")
    assert "Java method" in dense
    assert "Java method" not in bm25


def test_small_source_not_truncated(caplog) -> None:
    sym = _sym_with_source("def fn(): return 1")
    with caplog.at_level(logging.WARNING):
        text = _build_embedding_text(sym, "svc", max_chars=6000)
    assert _TRUNCATION_MARKER not in text
    assert "def fn(): return 1" in text
    assert not caplog.records


def test_oversized_source_truncated_and_logged(caplog) -> None:
    sym = _sym_with_source("x" * 10_000)
    with caplog.at_level(logging.WARNING):
        text = _build_embedding_text(sym, "svc", max_chars=6000)
    assert _TRUNCATION_MARKER in text
    # Whole text is bounded by max_chars (plus the short marker), not just the source.
    assert len(text) <= 6000 + len(_TRUNCATION_MARKER) + 1
    assert any("Truncating embedding source" in r.message for r in caplog.records)


def test_preamble_counts_against_budget() -> None:
    # Same source and max_chars, but a long preamble (docstring, capped at 300 chars)
    # eats into the budget, tipping a source that fits bare over the limit.
    source = "y" * 5_800
    bare = _build_embedding_text(_sym_with_source(source), "svc", max_chars=6000)
    with_preamble = _build_embedding_text(
        _sym_with_source(source, docstring="d" * 300), "svc", max_chars=6000
    )
    assert _TRUNCATION_MARKER not in bare
    assert _TRUNCATION_MARKER in with_preamble


def test_max_chars_is_configurable() -> None:
    sym = _sym_with_source("z" * 5_000)
    assert _TRUNCATION_MARKER not in _build_embedding_text(sym, "svc", max_chars=6000)
    assert _TRUNCATION_MARKER in _build_embedding_text(sym, "svc", max_chars=1000)


async def test_parser_failure_preserves_existing_index_entries() -> None:
    svc = ServiceConfig(name="svc", github_repo="org/repo", exclude=[])
    github_file = GitHubFile(rel_path="broken.py", blob_sha="sha1")

    store = AsyncMock()
    store.get_indexed_file_hashes.return_value = {"svc/broken.py": "old-sha"}

    pipeline = _make_pipeline(store)

    with (
        patch.object(
            type(pipeline_module.settings), "load_services", return_value=[svc]
        ),
        patch.object(
            pipeline_module, "list_github_files", AsyncMock(return_value=[github_file])
        ),
        patch.object(
            pipeline_module, "fetch_blob_content", AsyncMock(return_value=b"garbage")
        ),
        patch.object(
            pipeline_module, "parse_file", side_effect=ParseError("svc/broken.py")
        ),
    ):
        result = await pipeline.index_service("svc", force=True)

    store.delete_by_file.assert_not_called()
    store.upsert_chunks.assert_not_called()
    assert result["files"] == 0


async def test_unchanged_file_is_skipped_without_fetching_content() -> None:
    svc = ServiceConfig(name="svc", github_repo="org/repo", exclude=[])
    github_file = GitHubFile(rel_path="unchanged.py", blob_sha="same-sha")

    store = AsyncMock()
    store.get_indexed_file_hashes.return_value = {"svc/unchanged.py": "same-sha"}

    pipeline = _make_pipeline(store)

    with (
        patch.object(
            type(pipeline_module.settings), "load_services", return_value=[svc]
        ),
        patch.object(
            pipeline_module, "list_github_files", AsyncMock(return_value=[github_file])
        ),
        patch.object(pipeline_module, "fetch_blob_content", AsyncMock()) as mock_fetch,
    ):
        result = await pipeline.index_service("svc", force=False)

    mock_fetch.assert_not_called()
    store.delete_by_file.assert_not_called()
    assert result == {"files": 0, "chunks": 0, "skipped": 1}


async def test_force_reindexes_even_when_hash_unchanged() -> None:
    svc = ServiceConfig(name="svc", github_repo="org/repo", exclude=[])
    github_file = GitHubFile(rel_path="unchanged.py", blob_sha="same-sha")
    symbol = CodeSymbol(
        name="fn",
        symbol_type="function",
        language="python",
        source="def fn(): pass",
        file_path="svc/unchanged.py",
        start_line=1,
        end_line=1,
    )

    store = AsyncMock()
    store.get_indexed_file_hashes.return_value = {"svc/unchanged.py": "same-sha"}

    pipeline = _make_pipeline(store)

    with (
        patch.object(
            type(pipeline_module.settings), "load_services", return_value=[svc]
        ),
        patch.object(
            pipeline_module, "list_github_files", AsyncMock(return_value=[github_file])
        ),
        patch.object(
            pipeline_module,
            "fetch_blob_content",
            AsyncMock(return_value=b"def fn(): pass"),
        ),
        patch.object(pipeline_module, "parse_file", return_value=[symbol]),
    ):
        result = await pipeline.index_service("svc", force=True)

    store.delete_by_file.assert_called_once_with("svc", "svc/unchanged.py")
    store.upsert_chunks.assert_called_once()
    assert result == {"files": 1, "chunks": 1, "skipped": 0}


async def test_stale_index_entries_removed_when_file_no_longer_in_repo() -> None:
    svc = ServiceConfig(name="svc", github_repo="org/repo", exclude=[])

    store = AsyncMock()
    store.get_indexed_file_hashes.return_value = {
        "svc/deleted.py": "old-sha",
        "svc/still-there.py": "sha",
    }

    pipeline = _make_pipeline(store)

    with (
        patch.object(
            type(pipeline_module.settings), "load_services", return_value=[svc]
        ),
        patch.object(
            pipeline_module,
            "list_github_files",
            AsyncMock(
                return_value=[GitHubFile(rel_path="still-there.py", blob_sha="sha")]
            ),
        ),
    ):
        result = await pipeline.index_service("svc", force=False)

    store.delete_by_file.assert_called_once_with("svc", "svc/deleted.py")
    assert result["skipped"] == 1


async def test_file_with_no_symbols_deletes_stale_entries_and_skips_upsert() -> None:
    svc = ServiceConfig(name="svc", github_repo="org/repo", exclude=[])
    github_file = GitHubFile(rel_path="empty.py", blob_sha="sha1")

    store = AsyncMock()
    store.get_indexed_file_hashes.return_value = {}

    pipeline = _make_pipeline(store)

    with (
        patch.object(
            type(pipeline_module.settings), "load_services", return_value=[svc]
        ),
        patch.object(
            pipeline_module, "list_github_files", AsyncMock(return_value=[github_file])
        ),
        patch.object(
            pipeline_module, "fetch_blob_content", AsyncMock(return_value=b"")
        ),
        patch.object(pipeline_module, "parse_file", return_value=[]),
    ):
        result = await pipeline.index_service("svc", force=True)

    store.delete_by_file.assert_called_once_with("svc", "svc/empty.py")
    store.upsert_chunks.assert_not_called()
    assert result["files"] == 0


async def test_embedding_failure_preserves_existing_index_entries() -> None:
    svc = ServiceConfig(name="svc", github_repo="org/repo", exclude=[])
    github_file = GitHubFile(rel_path="broken.py", blob_sha="sha1")
    symbol = CodeSymbol(
        name="fn",
        symbol_type="function",
        language="python",
        source="def fn(): pass",
        file_path="svc/broken.py",
        start_line=1,
        end_line=1,
    )

    store = AsyncMock()
    store.get_indexed_file_hashes.return_value = {"svc/broken.py": "old-sha"}

    pipeline = _make_pipeline(store)
    pipeline._embedder.embed_batch = AsyncMock(side_effect=RuntimeError("503"))

    with (
        patch.object(
            type(pipeline_module.settings), "load_services", return_value=[svc]
        ),
        patch.object(
            pipeline_module, "list_github_files", AsyncMock(return_value=[github_file])
        ),
        patch.object(
            pipeline_module,
            "fetch_blob_content",
            AsyncMock(return_value=b"def fn(): pass"),
        ),
        patch.object(pipeline_module, "parse_file", return_value=[symbol]),
    ):
        result = await pipeline.index_service("svc", force=True)

    store.delete_by_file.assert_not_called()
    store.upsert_chunks.assert_not_called()
    assert result["files"] == 0


async def test_delete_by_file_called_before_upsert_for_changed_file() -> None:
    svc = ServiceConfig(name="svc", github_repo="org/repo", exclude=[])
    github_file = GitHubFile(rel_path="mod.py", blob_sha="new-sha")
    symbol = CodeSymbol(
        name="fn",
        symbol_type="function",
        language="python",
        source="def fn(): pass",
        file_path="svc/mod.py",
        start_line=1,
        end_line=1,
    )

    call_order: list[str] = []
    store = AsyncMock()
    store.get_indexed_file_hashes.return_value = {"svc/mod.py": "old-sha"}
    store.delete_by_file.side_effect = lambda *a, **k: call_order.append("delete")
    store.upsert_chunks.side_effect = lambda *a, **k: call_order.append("upsert")

    pipeline = _make_pipeline(store)

    with (
        patch.object(
            type(pipeline_module.settings), "load_services", return_value=[svc]
        ),
        patch.object(
            pipeline_module, "list_github_files", AsyncMock(return_value=[github_file])
        ),
        patch.object(
            pipeline_module,
            "fetch_blob_content",
            AsyncMock(return_value=b"def fn(): pass"),
        ),
        patch.object(pipeline_module, "parse_file", return_value=[symbol]),
    ):
        await pipeline.index_service("svc", force=False)

    assert call_order == ["delete", "upsert"]


async def test_unknown_service_returns_error_without_touching_github() -> None:
    pipeline = _make_pipeline(AsyncMock())

    with patch.object(type(pipeline_module.settings), "load_services", return_value=[]):
        result = await pipeline.index_service("missing")

    assert result == {"error": 1, "files": 0, "chunks": 0}
