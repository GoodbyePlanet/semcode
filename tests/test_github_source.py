from __future__ import annotations

import httpx
import respx

from server.indexer.github_source import list_github_files

_API = "https://api.github.com"
_REPO = "owner/repo"
_REF = "main"


def _tree_url(sha: str) -> str:
    return f"{_API}/repos/{_REPO}/git/trees/{sha}"


@respx.mock
async def test_non_truncated_filters_blobs() -> None:
    respx.get(_tree_url(_REF)).mock(
        return_value=httpx.Response(
            200,
            json={
                "sha": "roottree",
                "truncated": False,
                "tree": [
                    {"path": "src/main.py", "type": "blob", "sha": "a"},
                    {"path": "README.md", "type": "blob", "sha": "b"},
                    {"path": "notes.txt", "type": "blob", "sha": "c"},
                    {"path": "src", "type": "tree", "sha": "t1"},
                ],
            },
        )
    )

    files = await list_github_files("tok", _REPO, _REF, "svc", exclude=[])

    by_path = {f.rel_path: f.blob_sha for f in files}
    assert by_path == {"src/main.py": "a", "README.md": "b"}


@respx.mock
async def test_non_truncated_applies_root_and_exclude() -> None:
    respx.get(_tree_url(_REF)).mock(
        return_value=httpx.Response(
            200,
            json={
                "sha": "roottree",
                "truncated": False,
                "tree": [
                    {"path": "src/app.py", "type": "blob", "sha": "a"},
                    {"path": "src/test_app.py", "type": "blob", "sha": "b"},
                    {"path": "docs/guide.py", "type": "blob", "sha": "c"},
                ],
            },
        )
    )

    files = await list_github_files(
        "tok", _REPO, _REF, "svc", exclude=["test_*.py"], root="src"
    )

    by_path = {f.rel_path: f.blob_sha for f in files}
    assert by_path == {"app.py": "a"}


@respx.mock
async def test_truncated_falls_back_to_recursive_walk() -> None:
    # Recursive response is truncated and omits src/util.py entirely.
    respx.get(_tree_url(_REF)).mock(
        return_value=httpx.Response(
            200,
            json={
                "sha": "roottree",
                "truncated": True,
                "tree": [{"path": "main.py", "type": "blob", "sha": "m"}],
            },
        )
    )
    respx.get(_tree_url("roottree")).mock(
        return_value=httpx.Response(
            200,
            json={
                "truncated": False,
                "tree": [
                    {"path": "main.py", "type": "blob", "sha": "m"},
                    {"path": "src", "type": "tree", "sha": "t_src"},
                ],
            },
        )
    )
    respx.get(_tree_url("t_src")).mock(
        return_value=httpx.Response(
            200,
            json={
                "truncated": False,
                "tree": [
                    {"path": "app.py", "type": "blob", "sha": "app"},
                    {"path": "util.py", "type": "blob", "sha": "u"},
                ],
            },
        )
    )

    files = await list_github_files("tok", _REPO, _REF, "svc", exclude=[])

    by_path = {f.rel_path: f.blob_sha for f in files}
    assert by_path == {"main.py": "m", "src/app.py": "app", "src/util.py": "u"}


@respx.mock
async def test_truncated_walk_prunes_subtrees_outside_root() -> None:
    respx.get(_tree_url(_REF)).mock(
        return_value=httpx.Response(
            200, json={"sha": "roottree", "truncated": True, "tree": []}
        )
    )
    respx.get(_tree_url("roottree")).mock(
        return_value=httpx.Response(
            200,
            json={
                "truncated": False,
                "tree": [
                    {"path": "src", "type": "tree", "sha": "t_src"},
                    {"path": "docs", "type": "tree", "sha": "t_docs"},
                ],
            },
        )
    )
    src_route = respx.get(_tree_url("t_src")).mock(
        return_value=httpx.Response(
            200,
            json={
                "truncated": False,
                "tree": [{"path": "app.py", "type": "blob", "sha": "app"}],
            },
        )
    )
    docs_route = respx.get(_tree_url("t_docs")).mock(
        return_value=httpx.Response(
            200,
            json={
                "truncated": False,
                "tree": [{"path": "guide.py", "type": "blob", "sha": "g"}],
            },
        )
    )

    files = await list_github_files("tok", _REPO, _REF, "svc", exclude=[], root="src")

    by_path = {f.rel_path: f.blob_sha for f in files}
    assert by_path == {"app.py": "app"}
    assert src_route.called
    assert not docs_route.called
