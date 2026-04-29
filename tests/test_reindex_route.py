from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from mcp.server.fastmcp import FastMCP

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



async def test_reindex_all_no_body(client, mock_pipeline):
    store_patch = patch("server.routes.reindex.get_store", return_value=MagicMock())
    pipeline_patch = patch("server.routes.reindex.IndexPipeline", return_value=mock_pipeline)
    with store_patch, pipeline_patch:
        response = await client.post("/reindex")

    assert response.status_code == 200
    assert response.json() == ALL_RESULT
    mock_pipeline.index_all.assert_called_once_with(force=False)
    mock_pipeline.index_service.assert_not_called()


async def test_reindex_all_empty_json(client, mock_pipeline):
    store_patch = patch("server.routes.reindex.get_store", return_value=MagicMock())
    pipeline_patch = patch("server.routes.reindex.IndexPipeline", return_value=mock_pipeline)
    with store_patch, pipeline_patch:
        response = await client.post("/reindex", json={})

    assert response.status_code == 200
    assert response.json() == ALL_RESULT
    mock_pipeline.index_all.assert_called_once_with(force=False)


async def test_reindex_single_service(client, mock_pipeline):
    store_patch = patch("server.routes.reindex.get_store", return_value=MagicMock())
    pipeline_patch = patch("server.routes.reindex.IndexPipeline", return_value=mock_pipeline)
    with store_patch, pipeline_patch:
        response = await client.post("/reindex", json={"service": "svc-a"})

    assert response.status_code == 200
    assert response.json() == SERVICE_RESULT
    mock_pipeline.index_service.assert_called_once_with("svc-a", force=False)
    mock_pipeline.index_all.assert_not_called()


async def test_reindex_single_service_with_force(client, mock_pipeline):
    store_patch = patch("server.routes.reindex.get_store", return_value=MagicMock())
    pipeline_patch = patch("server.routes.reindex.IndexPipeline", return_value=mock_pipeline)
    with store_patch, pipeline_patch:
        response = await client.post("/reindex", json={"service": "svc-a", "force": True})

    assert response.status_code == 200
    mock_pipeline.index_service.assert_called_once_with("svc-a", force=True)


async def test_reindex_all_with_force(client, mock_pipeline):
    store_patch = patch("server.routes.reindex.get_store", return_value=MagicMock())
    pipeline_patch = patch("server.routes.reindex.IndexPipeline", return_value=mock_pipeline)
    with store_patch, pipeline_patch:
        response = await client.post("/reindex", json={"force": True})

    assert response.status_code == 200
    mock_pipeline.index_all.assert_called_once_with(force=True)


async def test_reindex_unknown_service_returns_pipeline_result(client, mock_pipeline):
    mock_pipeline.index_service.return_value = {"error": 1}
    store_patch = patch("server.routes.reindex.get_store", return_value=MagicMock())
    pipeline_patch = patch("server.routes.reindex.IndexPipeline", return_value=mock_pipeline)
    with store_patch, pipeline_patch:
        response = await client.post("/reindex", json={"service": "unknown"})

    assert response.status_code == 200
    assert response.json() == {"error": 1}
