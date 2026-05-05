from __future__ import annotations

import json as json_module
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import httpx
import pytest
from mcp.server.fastmcp import FastMCP

from server.indexer.pipeline import ProgressEvent
from server.routes.reindex import register_http_routes

SERVICE_RESULT = {"files": 10, "chunks": 50, "skipped": 2}
ALL_RESULT = {"svc-a": SERVICE_RESULT, "svc-b": {"files": 5, "chunks": 20, "skipped": 0}}


@pytest.fixture
def app():
    mcp = FastMCP("test")
    register_http_routes(mcp)
    return mcp.streamable_http_app()


@pytest.fixture
async def client(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        yield c


@pytest.fixture
def mock_pipeline():
    pipeline = AsyncMock()
    pipeline.index_service.return_value = SERVICE_RESULT
    pipeline.index_all.return_value = ALL_RESULT
    return pipeline


def _parse_ndjson(text: str) -> list[dict]:
    return [json_module.loads(ln) for ln in text.strip().split("\n") if ln]


def _done_result(text: str) -> dict:
    frames = _parse_ndjson(text)
    done = [f for f in frames if f["type"] == "done"]
    assert len(done) == 1
    return done[0]["result"]


async def test_reindex_all_no_body(client, mock_pipeline):
    store_patch = patch("server.routes.reindex.get_store", return_value=MagicMock())
    pipeline_patch = patch("server.routes.reindex.IndexPipeline", return_value=mock_pipeline)
    with store_patch, pipeline_patch:
        response = await client.post("/reindex")

    assert response.status_code == 200
    assert _done_result(response.text) == ALL_RESULT
    mock_pipeline.index_all.assert_called_once_with(force=False, progress_callback=ANY)
    mock_pipeline.index_service.assert_not_called()


async def test_reindex_all_empty_json(client, mock_pipeline):
    store_patch = patch("server.routes.reindex.get_store", return_value=MagicMock())
    pipeline_patch = patch("server.routes.reindex.IndexPipeline", return_value=mock_pipeline)
    with store_patch, pipeline_patch:
        response = await client.post("/reindex", json={})

    assert response.status_code == 200
    assert _done_result(response.text) == ALL_RESULT
    mock_pipeline.index_all.assert_called_once_with(force=False, progress_callback=ANY)


async def test_reindex_single_service(client, mock_pipeline):
    store_patch = patch("server.routes.reindex.get_store", return_value=MagicMock())
    pipeline_patch = patch("server.routes.reindex.IndexPipeline", return_value=mock_pipeline)
    with store_patch, pipeline_patch:
        response = await client.post("/reindex", json={"service": "svc-a"})

    assert response.status_code == 200
    assert _done_result(response.text) == SERVICE_RESULT
    mock_pipeline.index_service.assert_called_once_with("svc-a", force=False, progress_callback=ANY)
    mock_pipeline.index_all.assert_not_called()


async def test_reindex_single_service_with_force(client, mock_pipeline):
    store_patch = patch("server.routes.reindex.get_store", return_value=MagicMock())
    pipeline_patch = patch("server.routes.reindex.IndexPipeline", return_value=mock_pipeline)
    with store_patch, pipeline_patch:
        response = await client.post("/reindex", json={"service": "svc-a", "force": True})

    assert response.status_code == 200
    mock_pipeline.index_service.assert_called_once_with("svc-a", force=True, progress_callback=ANY)


async def test_reindex_all_with_force(client, mock_pipeline):
    store_patch = patch("server.routes.reindex.get_store", return_value=MagicMock())
    pipeline_patch = patch("server.routes.reindex.IndexPipeline", return_value=mock_pipeline)
    with store_patch, pipeline_patch:
        response = await client.post("/reindex", json={"force": True})

    assert response.status_code == 200
    mock_pipeline.index_all.assert_called_once_with(force=True, progress_callback=ANY)


async def test_reindex_emits_progress_and_done(client):
    sample_event = ProgressEvent(phase="upserting", current=5, total=10, percentage=50.0, service="svc-a")

    async def fake_index_service(service_name, force=False, progress_callback=None):
        if progress_callback:
            await progress_callback(sample_event)
        return SERVICE_RESULT

    mock = AsyncMock()
    mock.index_service = fake_index_service

    store_patch = patch("server.routes.reindex.get_store", return_value=MagicMock())
    pipeline_patch = patch("server.routes.reindex.IndexPipeline", return_value=mock)

    with store_patch, pipeline_patch:
        response = await client.post("/reindex", json={"service": "svc-a"})

    assert response.status_code == 200
    frames = _parse_ndjson(response.text)

    progress_frames = [f for f in frames if f["type"] == "progress"]
    done_frames = [f for f in frames if f["type"] == "done"]

    assert len(progress_frames) >= 1
    assert progress_frames[0]["phase"] == "upserting"
    assert progress_frames[0]["service"] == "svc-a"
    assert progress_frames[0]["current"] == 5
    assert progress_frames[0]["total"] == 10
    assert len(done_frames) == 1
    assert done_frames[0]["result"] == SERVICE_RESULT


async def test_reindex_unknown_service_returns_pipeline_result(client, mock_pipeline):
    mock_pipeline.index_service.return_value = {"error": 1}
    store_patch = patch("server.routes.reindex.get_store", return_value=MagicMock())
    pipeline_patch = patch("server.routes.reindex.IndexPipeline", return_value=mock_pipeline)
    with store_patch, pipeline_patch:
        response = await client.post("/reindex", json={"service": "unknown"})

    assert response.status_code == 200
    assert _done_result(response.text) == {"error": 1}


HISTORY_SERVICE_RESULT = {"new": 25, "skipped": 0}
HISTORY_ALL_RESULT = {"svc-a": HISTORY_SERVICE_RESULT, "svc-b": {"new": 10, "skipped": 5}}


@pytest.fixture
def mock_history_pipeline():
    pipeline = AsyncMock()
    pipeline.index_service.return_value = HISTORY_SERVICE_RESULT
    pipeline.index_all.return_value = HISTORY_ALL_RESULT
    return pipeline


async def test_reindex_history_all_no_body(client, mock_history_pipeline):
    store_patch = patch("server.routes.reindex.get_commit_store", return_value=MagicMock())
    pipeline_patch = patch("server.routes.reindex.GitHistoryPipeline", return_value=mock_history_pipeline)
    with store_patch, pipeline_patch:
        response = await client.post("/reindex-history")

    assert response.status_code == 200
    assert _done_result(response.text) == HISTORY_ALL_RESULT
    mock_history_pipeline.index_all.assert_called_once_with(force=False, progress_callback=ANY)
    mock_history_pipeline.index_service.assert_not_called()


async def test_reindex_history_single_service(client, mock_history_pipeline):
    store_patch = patch("server.routes.reindex.get_commit_store", return_value=MagicMock())
    pipeline_patch = patch("server.routes.reindex.GitHistoryPipeline", return_value=mock_history_pipeline)
    with store_patch, pipeline_patch:
        response = await client.post("/reindex-history", json={"service": "svc-a"})

    assert response.status_code == 200
    assert _done_result(response.text) == HISTORY_SERVICE_RESULT
    mock_history_pipeline.index_service.assert_called_once_with("svc-a", force=False, progress_callback=ANY)
    mock_history_pipeline.index_all.assert_not_called()


async def test_reindex_history_with_force(client, mock_history_pipeline):
    store_patch = patch("server.routes.reindex.get_commit_store", return_value=MagicMock())
    pipeline_patch = patch("server.routes.reindex.GitHistoryPipeline", return_value=mock_history_pipeline)
    with store_patch, pipeline_patch:
        response = await client.post("/reindex-history", json={"service": "svc-a", "force": True})

    assert response.status_code == 200
    mock_history_pipeline.index_service.assert_called_once_with("svc-a", force=True, progress_callback=ANY)


async def test_reindex_history_emits_progress_and_done(client):
    sample_event = ProgressEvent(phase="embedding", current=25, total=25, percentage=100.0, service="svc-a")

    async def fake_index_service(service_name, force=False, progress_callback=None):
        if progress_callback:
            await progress_callback(sample_event)
        return HISTORY_SERVICE_RESULT

    mock = AsyncMock()
    mock.index_service = fake_index_service

    store_patch = patch("server.routes.reindex.get_commit_store", return_value=MagicMock())
    pipeline_patch = patch("server.routes.reindex.GitHistoryPipeline", return_value=mock)

    with store_patch, pipeline_patch:
        response = await client.post("/reindex-history", json={"service": "svc-a"})

    assert response.status_code == 200
    frames = _parse_ndjson(response.text)

    progress_frames = [f for f in frames if f["type"] == "progress"]
    done_frames = [f for f in frames if f["type"] == "done"]

    assert len(progress_frames) >= 1
    assert progress_frames[0]["phase"] == "embedding"
    assert progress_frames[0]["service"] == "svc-a"
    assert len(done_frames) == 1
    assert done_frames[0]["result"] == HISTORY_SERVICE_RESULT
