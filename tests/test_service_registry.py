from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from server.config import ServiceConfig, settings
from server.store.service_registry import ServiceRegistry, load_effective_services


def _make_registry() -> ServiceRegistry:
    registry = ServiceRegistry.__new__(ServiceRegistry)
    registry._client = MagicMock()
    return registry


def _point(payload: dict) -> SimpleNamespace:
    return SimpleNamespace(payload=payload)


async def test_list_all_returns_empty_when_collection_missing() -> None:
    registry = _make_registry()
    registry._client.collection_exists = AsyncMock(return_value=False)

    services = await registry.list_all()

    assert services == []


async def test_upsert_creates_collection_then_writes_point() -> None:
    registry = _make_registry()
    registry._client.collection_exists = AsyncMock(return_value=False)
    registry._client.create_collection = AsyncMock()
    registry._client.upsert = AsyncMock()

    svc = ServiceConfig(
        name="adhoc", github_repo="org/adhoc", github_ref="main", root=None, exclude=[]
    )
    await registry.upsert(svc)

    registry._client.create_collection.assert_awaited_once()
    registry._client.upsert.assert_awaited_once()
    _, kwargs = registry._client.upsert.call_args
    point = kwargs["points"][0]
    assert point.payload["name"] == "adhoc"
    assert point.payload["github_repo"] == "org/adhoc"
    assert point.payload["github_ref"] == "main"


async def test_list_all_paginates_and_converts_payloads() -> None:
    registry = _make_registry()
    registry._client.collection_exists = AsyncMock(return_value=True)

    page1 = [_point({"name": "a", "github_repo": "org/a", "github_ref": "main"})]
    page2 = [
        _point(
            {
                "name": "b",
                "github_repo": "org/b",
                "github_ref": "dev",
                "root": "src",
                "exclude": ["**/vendor/**"],
            }
        )
    ]
    registry._client.scroll = AsyncMock(side_effect=[(page1, "cursor"), (page2, None)])

    services = await registry.list_all()

    assert [s.name for s in services] == ["a", "b"]
    assert services[1].root == "src"
    assert services[1].exclude == ["**/vendor/**"]


async def test_load_effective_services_merges_config_and_registry() -> None:
    registry = AsyncMock()
    registry.list_all = AsyncMock(
        return_value=[ServiceConfig(name="adhoc", github_repo="org/adhoc", exclude=[])]
    )

    with patch.object(
        type(settings),
        "load_services",
        return_value=[
            ServiceConfig(name="curated", github_repo="org/curated", exclude=[])
        ],
    ):
        services = await load_effective_services(registry)

    names = {s.name for s in services}
    assert names == {"adhoc", "curated"}


async def test_load_effective_services_config_yaml_wins_on_name_collision() -> None:
    registry = AsyncMock()
    registry.list_all = AsyncMock(
        return_value=[
            ServiceConfig(name="shared", github_repo="attacker/repo", exclude=[])
        ]
    )

    with patch.object(
        type(settings),
        "load_services",
        return_value=[
            ServiceConfig(name="shared", github_repo="org/legit", exclude=[])
        ],
    ):
        services = await load_effective_services(registry)

    assert len(services) == 1
    assert services[0].github_repo == "org/legit"
