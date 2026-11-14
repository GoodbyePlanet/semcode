from __future__ import annotations

import httpx
import pytest
import respx

from server.config import settings
from server.indexer.sources import common
from server.indexer.sources.gitlab import GitLabSource, _count_changes

_API = "https://gitlab.com/api/v4"
_REPO = "group/sub/project"
_PROJECT = f"{_API}/projects/group%2Fsub%2Fproject"


@pytest.fixture
def no_sleep(monkeypatch):
    """Record backoff waits instead of serving them."""
    waits: list[float] = []

    async def _sleep(seconds: float) -> None:
        waits.append(seconds)

    monkeypatch.setattr(common.asyncio, "sleep", _sleep)
    return waits


def _item(path: str, sha: str, type_: str = "blob") -> dict:
    return {"id": sha, "name": path.split("/")[-1], "type": type_, "path": path}


def _commit(sha: str) -> dict:
    return {
        "id": sha,
        "message": f"message {sha}",
        "author_name": "Ada",
        "author_email": "ada@example.com",
        "authored_date": "2026-01-02T03:04:05.000+00:00",
    }


@respx.mock
async def test_list_files_returns_supported_blobs_with_shas() -> None:
    route = respx.get(f"{_PROJECT}/repository/tree").mock(
        return_value=httpx.Response(
            200,
            json=[
                _item("src/Foo.java", "sha-foo"),
                _item("src", "sha-dir", "tree"),
                _item("logo.png", "sha-png"),
            ],
        )
    )

    files = await GitLabSource("tok", _REPO).list_files("main", [])

    assert [(f.rel_path, f.blob_sha) for f in files] == [("src/Foo.java", "sha-foo")]
    request = route.calls.last.request
    assert request.headers["PRIVATE-TOKEN"] == "tok"
    assert request.url.params["ref"] == "main"
    assert request.url.params["recursive"] == "true"


@respx.mock
async def test_list_files_follows_keyset_pagination_links() -> None:
    next_url = f"{_PROJECT}/repository/tree?pagination=keyset&page_token=abc"
    respx.get(f"{_PROJECT}/repository/tree", params={"page_token": "abc"}).mock(
        return_value=httpx.Response(200, json=[_item("b.py", "sha-b")])
    )
    respx.get(f"{_PROJECT}/repository/tree").mock(
        return_value=httpx.Response(
            200,
            json=[_item("a.py", "sha-a")],
            headers={"Link": f'<{next_url}>; rel="next"'},
        )
    )

    files = await GitLabSource("tok", _REPO).list_files("main", [])

    assert [f.rel_path for f in files] == ["a.py", "b.py"]


@respx.mock
async def test_list_files_falls_back_to_offset_pagination() -> None:
    respx.get(f"{_PROJECT}/repository/tree", params={"page": "2"}).mock(
        return_value=httpx.Response(200, json=[_item("b.py", "sha-b")])
    )
    respx.get(f"{_PROJECT}/repository/tree").mock(
        return_value=httpx.Response(
            200, json=[_item("a.py", "sha-a")], headers={"X-Next-Page": "2"}
        )
    )

    files = await GitLabSource("tok", _REPO).list_files("main", [])

    assert [f.rel_path for f in files] == ["a.py", "b.py"]


@respx.mock
async def test_list_files_scopes_to_root_and_applies_exclude() -> None:
    route = respx.get(f"{_PROJECT}/repository/tree").mock(
        return_value=httpx.Response(
            200,
            json=[
                _item("svc/src/Foo.java", "sha-foo"),
                _item("svc/test/FooTest.java", "sha-test"),
                _item("other/Bar.java", "sha-bar"),
            ],
        )
    )

    files = await GitLabSource("tok", _REPO).list_files(
        "main", ["**/test/**"], root="svc/"
    )

    assert [f.rel_path for f in files] == ["src/Foo.java"]
    assert route.calls.last.request.url.params["path"] == "svc"


@respx.mock
async def test_numeric_project_id_is_used_as_is() -> None:
    route = respx.get(f"{_API}/projects/42/repository/tree").mock(
        return_value=httpx.Response(200, json=[])
    )

    await GitLabSource("tok", "42").list_files("main", [])

    assert route.called


@respx.mock
async def test_requests_omit_auth_header_without_token() -> None:
    route = respx.get(f"{_PROJECT}/repository/tree").mock(
        return_value=httpx.Response(200, json=[])
    )

    await GitLabSource("", _REPO).list_files("main", [])

    assert "PRIVATE-TOKEN" not in route.calls.last.request.headers


@respx.mock
async def test_fetch_blob_returns_raw_bytes() -> None:
    respx.get(f"{_PROJECT}/repository/blobs/deadbeef/raw").mock(
        return_value=httpx.Response(200, content=b"\x00raw bytes\n")
    )

    content = await GitLabSource("tok", _REPO).fetch_blob("deadbeef")

    assert content == b"\x00raw bytes\n"


@respx.mock
async def test_fetch_file_url_encodes_path_and_passes_ref() -> None:
    route = respx.get(
        f"{_PROJECT}/repository/files/services%2Forders%2FOrder.java/raw"
    ).mock(return_value=httpx.Response(200, content=b"class Order {}"))

    content = await GitLabSource("tok", _REPO).fetch_file(
        "services/orders/Order.java", "release/1.0"
    )

    assert content == b"class Order {}"
    assert route.calls.last.request.url.params["ref"] == "release/1.0"


@respx.mock
async def test_list_commits_maps_fields_and_filters_by_path() -> None:
    route = respx.get(f"{_PROJECT}/repository/commits").mock(
        return_value=httpx.Response(200, json=[_commit("c1"), _commit("c2")])
    )

    commits = await GitLabSource("tok", _REPO).list_commits("main", root="svc")

    assert [c.sha for c in commits] == ["c1", "c2"]
    assert commits[0].author_name == "Ada"
    assert commits[0].author_email == "ada@example.com"
    assert commits[0].committed_at == "2026-01-02T03:04:05.000+00:00"
    params = route.calls.last.request.url.params
    assert params["ref_name"] == "main"
    assert params["path"] == "svc"


@respx.mock
async def test_list_commits_stops_at_max_commits() -> None:
    respx.get(f"{_PROJECT}/repository/commits", params={"page": "2"}).mock(
        return_value=httpx.Response(200, json=[_commit("c3"), _commit("c4")])
    )
    respx.get(f"{_PROJECT}/repository/commits").mock(
        return_value=httpx.Response(
            200, json=[_commit("c1"), _commit("c2")], headers={"X-Next-Page": "2"}
        )
    )

    commits = await GitLabSource("tok", _REPO).list_commits("main", max_commits=3)

    assert [c.sha for c in commits] == ["c1", "c2", "c3"]


@respx.mock
async def test_fetch_commits_with_diffs_maps_status_and_counts_changes() -> None:
    respx.get(f"{_PROJECT}/repository/commits/c1/diff").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "new_path": "A.java",
                    "old_path": "A.java",
                    "new_file": True,
                    "renamed_file": False,
                    "deleted_file": False,
                    "diff": "@@ -0,0 +1,2 @@\n+one\n+two\n",
                },
                {
                    "new_path": "B.java",
                    "old_path": "B.java",
                    "new_file": False,
                    "renamed_file": False,
                    "deleted_file": True,
                    "diff": "@@ -1 +0,0 @@\n-gone\n",
                },
                {
                    "new_path": "C.java",
                    "old_path": "Old.java",
                    "new_file": False,
                    "renamed_file": True,
                    "deleted_file": False,
                    "diff": "",
                },
            ],
        )
    )
    source = GitLabSource("tok", _REPO)
    (commit,) = await source.fetch_commits_with_diffs(
        await _commits(source, [_commit("c1")])
    )

    by_name = {f.filename: f for f in commit.files}
    assert (by_name["A.java"].status, by_name["A.java"].additions) == ("added", 2)
    assert (by_name["B.java"].status, by_name["B.java"].deletions) == ("deleted", 1)
    assert by_name["C.java"].status == "renamed"
    assert by_name["C.java"].patch is None


async def _commits(source: GitLabSource, raw: list[dict]):
    with respx.mock:
        respx.get(f"{_PROJECT}/repository/commits").mock(
            return_value=httpx.Response(200, json=raw)
        )
        return await source.list_commits("main")


@respx.mock
async def test_fetch_commits_with_diffs_truncates_patches_and_files() -> None:
    respx.get(f"{_PROJECT}/repository/commits/c1/diff").mock(
        return_value=httpx.Response(
            200,
            json=[{"new_path": f"f{i}.py", "diff": "+" + "x" * 50} for i in range(3)],
        )
    )
    source = GitLabSource("tok", _REPO)
    (commit,) = await source.fetch_commits_with_diffs(
        await _commits(source, [_commit("c1")]), max_files=2, max_patch_chars=10
    )

    assert len(commit.files) == 2
    assert all(len(f.patch or "") == 10 for f in commit.files)


@respx.mock
async def test_diff_failure_keeps_commit_without_files() -> None:
    respx.get(f"{_PROJECT}/repository/commits/c1/diff").mock(
        return_value=httpx.Response(404)
    )
    source = GitLabSource("tok", _REPO)
    (commit,) = await source.fetch_commits_with_diffs(
        await _commits(source, [_commit("c1")])
    )

    assert commit.sha == "c1"
    assert commit.files == []


@respx.mock
async def test_rate_limit_waits_for_retry_after_then_succeeds(no_sleep) -> None:
    route = respx.get(f"{_PROJECT}/repository/blobs/deadbeef/raw").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "7"}),
            httpx.Response(200, content=b"ok"),
        ]
    )

    content = await GitLabSource("tok", _REPO).fetch_blob("deadbeef")

    assert content == b"ok"
    assert route.call_count == 2
    assert no_sleep == [7.0]


@respx.mock
async def test_rate_limit_without_hints_uses_default_wait(no_sleep) -> None:
    respx.get(f"{_PROJECT}/repository/blobs/deadbeef/raw").mock(
        side_effect=[httpx.Response(429), httpx.Response(200, content=b"ok")]
    )

    await GitLabSource("tok", _REPO).fetch_blob("deadbeef")

    assert no_sleep == [60.0]


@respx.mock
async def test_forbidden_is_not_retried(no_sleep) -> None:
    route = respx.get(f"{_PROJECT}/repository/blobs/deadbeef/raw").mock(
        return_value=httpx.Response(403)
    )

    with pytest.raises(httpx.HTTPStatusError):
        await GitLabSource("tok", _REPO).fetch_blob("deadbeef")

    assert route.call_count == 1
    assert no_sleep == []


@respx.mock
async def test_server_error_is_retried(no_sleep) -> None:
    route = respx.get(f"{_PROJECT}/repository/blobs/deadbeef/raw").mock(
        side_effect=[httpx.Response(502), httpx.Response(200, content=b"ok")]
    )

    content = await GitLabSource("tok", _REPO).fetch_blob("deadbeef")

    assert content == b"ok"
    assert route.call_count == 2
    assert no_sleep == [common.BACKOFF_DELAYS[0]]


@respx.mock
async def test_custom_gitlab_api_url(monkeypatch) -> None:
    monkeypatch.setattr(settings, "gitlab_api_url", "https://git.corp.example/api/v4/")
    route = respx.get(
        "https://git.corp.example/api/v4/projects/group%2Fproject/repository/tree"
    ).mock(return_value=httpx.Response(200, json=[]))

    await GitLabSource("tok", "group/project").list_files("main", [])

    assert route.called


@pytest.mark.parametrize(
    "diff,expected",
    [
        ("", (0, 0)),
        ("@@ -1 +1 @@\n-a\n+b\n", (1, 1)),
        ("@@ -1,2 +1 @@\n--- not a header\n context\n", (0, 1)),
    ],
)
def test_count_changes_counts_plus_and_minus_lines(diff, expected) -> None:
    assert _count_changes(diff) == expected
