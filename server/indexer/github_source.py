from __future__ import annotations

import asyncio
import base64
import logging
import time
from typing import Any

import httpx

from server.config import settings
from server.indexer.sources import common
from server.indexer.sources.base import CommitFile, SourceCommit, SourceFile
from server.indexer.sources.common import client_ctx as _client_ctx
from server.indexer.sources.common import filter_tree_blobs as _filter_tree_blobs

_DIFF_CONCURRENCY = 10
_TREE_WALK_CONCURRENCY = 10

# Backoff delays are shared with the other sources (see sources/common.py).
_GH_ATTEMPTS = common.ATTEMPTS
_GH_BACKOFF_DELAYS = common.BACKOFF_DELAYS

logger = logging.getLogger(__name__)


# Neutral models live in sources/base.py; the GitHub-specific names stay as aliases.
GitHubFile = SourceFile
GitHubCommit = SourceCommit


def _auth_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _github_rate_limit_wait(r: httpx.Response) -> float:
    """Seconds to wait per Retry-After / X-RateLimit-Reset, whichever is later."""
    reset_ts = float(r.headers.get("X-RateLimit-Reset", 0))
    retry_after = float(r.headers.get("Retry-After", 60))
    now = time.time()
    return max(retry_after, reset_ts - now if reset_ts > now else 0.0)


async def _gh_get(
    client: httpx.AsyncClient,
    url: str,
    token: str,
    params: dict | None = None,
    timeout: float = 30.0,
) -> Any:
    """GET a GitHub API URL, retrying rate limits (403/429), 5xx and transport errors.

    Rate limits wait for the window GitHub names via ``Retry-After`` /
    ``X-RateLimit-Reset``; see `common.get_with_retry` for the shared behavior.
    """
    r = await common.get_with_retry(
        client,
        url,
        _auth_headers(token),
        label="GitHub",
        rate_limit_statuses=(403, 429),
        rate_limit_wait=_github_rate_limit_wait,
        params=params,
        timeout=timeout,
    )
    return r.json()


def _subtree_is_relevant(dir_path: str, root_prefix: str | None) -> bool:
    """Whether a directory could contain files under *root_prefix* and is worth fetching.

    A directory is relevant when it lives under the root prefix, or is an ancestor of it.
    """
    if not root_prefix:
        return True
    dir_prefix = dir_path + "/"
    return dir_prefix.startswith(root_prefix) or root_prefix.startswith(dir_prefix)


async def _walk_tree_recursive(
    client: httpx.AsyncClient,
    repo: str,
    token: str,
    tree_sha: str,
    prefix: str,
    root_prefix: str | None,
    sem: asyncio.Semaphore,
) -> list[tuple[str, str]]:
    """Recursively list all blobs under *tree_sha* via non-recursive trees calls.

    Each single-directory listing is small and effectively never hits the Trees API size
    limit. Subtrees that cannot contain files under *root_prefix* are pruned. Sibling
    subtree fetches run concurrently, bounded by *sem*. Returns ``(full_path, blob_sha)``
    tuples.
    """
    async with sem:
        tree = await _gh_get(
            client,
            f"{settings.github_api_url.rstrip('/')}/repos/{repo}/git/trees/{tree_sha}",
            token,
            timeout=30,
        )

    if tree.get("truncated"):
        logger.warning(
            "GitHub trees response still truncated for subtree %s under %s — directory has "
            "too many entries; some files may be missing from the index.",
            tree_sha,
            prefix or "<root>",
        )

    blobs: list[tuple[str, str]] = []
    subtree_tasks = []
    for item in tree.get("tree", []):
        full_path = f"{prefix}{item['path']}"
        if item["type"] == "blob":
            blobs.append((full_path, item["sha"]))
        elif item["type"] == "tree" and _subtree_is_relevant(full_path, root_prefix):
            subtree_tasks.append(
                _walk_tree_recursive(
                    client,
                    repo,
                    token,
                    item["sha"],
                    f"{full_path}/",
                    root_prefix,
                    sem,
                )
            )

    for sub_blobs in await asyncio.gather(*subtree_tasks):
        blobs.extend(sub_blobs)
    return blobs


async def list_github_files(
    token: str,
    repo: str,
    ref: str,
    service_name: str,
    exclude: list[str],
    root: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> list[GitHubFile]:
    """List matching files via the git trees API.

    Uses a single recursive request for the full tree. If GitHub truncates that response
    (undocumented size limit on very large repos), falls back to a recursive per-subtree
    walk so no files are silently dropped.

    All files whose extension or basename is recognised by the parser registry are
    indexed. If *root* is set, only files under that path prefix are considered.
    Paths matching *exclude* patterns are skipped.
    """
    root_prefix = root.rstrip("/") + "/" if root else None

    async with _client_ctx(client) as c:
        tree = await _gh_get(
            c,
            f"{settings.github_api_url.rstrip('/')}/repos/{repo}/git/trees/{ref}",
            token,
            {"recursive": "1"},
            timeout=30,
        )

        if not tree.get("truncated"):
            blobs = [
                (item["path"], item["sha"])
                for item in tree.get("tree", [])
                if item["type"] == "blob"
            ]
            return _filter_tree_blobs(blobs, root_prefix, exclude)

        logger.info(
            "GitHub trees response truncated for %s@%s — falling back to recursive "
            "per-subtree walk.",
            repo,
            ref,
        )
        sem = asyncio.Semaphore(_TREE_WALK_CONCURRENCY)
        blobs = await _walk_tree_recursive(
            c, repo, token, tree["sha"], "", root_prefix, sem
        )

    return _filter_tree_blobs(blobs, root_prefix, exclude)


async def list_commits(
    token: str,
    repo: str,
    ref: str,
    root: str | None = None,
    max_commits: int = 500,
    client: httpx.AsyncClient | None = None,
) -> list[GitHubCommit]:
    """Fetch recent commits from the GitHub commits API, optionally filtered to a path prefix."""
    commits: list[GitHubCommit] = []
    page = 1
    per_page = 100

    async with _client_ctx(client) as c:
        while len(commits) < max_commits:
            params: dict[str, str | int] = {
                "sha": ref,
                "per_page": per_page,
                "page": page,
            }
            if root:
                params["path"] = root
            batch = await _gh_get(
                c,
                f"{settings.github_api_url.rstrip('/')}/repos/{repo}/commits",
                token,
                params,
            )
            if not batch:
                break
            for item in batch:
                commit_data = item["commit"]
                commits.append(
                    GitHubCommit(
                        sha=item["sha"],
                        message=commit_data["message"],
                        author_name=commit_data["author"]["name"],
                        author_email=commit_data["author"]["email"],
                        committed_at=commit_data["author"]["date"],
                    )
                )
            if len(batch) < per_page:
                break
            page += 1

    return commits[:max_commits]


async def fetch_commit_detail(
    token: str,
    repo: str,
    sha: str,
    client: httpx.AsyncClient | None = None,
) -> list[CommitFile]:
    """Fetch changed files for a single commit via GET /repos/{repo}/commits/{sha}."""
    async with _client_ctx(client) as c:
        data = await _gh_get(
            c,
            f"{settings.github_api_url.rstrip('/')}/repos/{repo}/commits/{sha}",
            token,
            timeout=30,
        )

    raw_files = data.get("files", [])
    if len(raw_files) >= 300:
        logger.warning(
            "Commit %s has >= 300 changed files — GitHub API limit reached, some files may be omitted.",
            sha[:8],
        )
    return [
        CommitFile(
            filename=f["filename"],
            status=f.get("status", "modified"),
            additions=f.get("additions", 0),
            deletions=f.get("deletions", 0),
            patch=f.get("patch"),
        )
        for f in raw_files
    ]


async def fetch_commits_with_diffs(
    token: str,
    repo: str,
    commits: list[GitHubCommit],
    max_files: int = 50,
    max_patch_chars: int = 2000,
    client: httpx.AsyncClient | None = None,
) -> list[GitHubCommit]:
    """Fetch diff details for a batch of commits in parallel, bounded by a semaphore."""

    async def _detail(sha: str, shared_client: httpx.AsyncClient) -> list[CommitFile]:
        return await fetch_commit_detail(token, repo, sha, client=shared_client)

    return await common.fetch_commits_with_diffs(
        commits,
        _detail,
        max_files=max_files,
        max_patch_chars=max_patch_chars,
        concurrency=_DIFF_CONCURRENCY,
        client=client,
    )


async def fetch_blob_content(
    token: str,
    repo: str,
    blob_sha: str,
    client: httpx.AsyncClient | None = None,
) -> bytes:
    """Fetch file content by git blob SHA. Used during indexing — avoids re-resolving paths."""
    async with _client_ctx(client) as c:
        data = await _gh_get(
            c,
            f"{settings.github_api_url.rstrip('/')}/repos/{repo}/git/blobs/{blob_sha}",
            token,
            timeout=60,
        )
    return base64.b64decode(data["content"].replace("\n", ""))


async def fetch_file_content(token: str, repo: str, path: str, ref: str) -> bytes:
    """Fetch file content by path and ref. Falls back to blob API for files > 1 MB."""
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{settings.github_api_url.rstrip('/')}/repos/{repo}/contents/{path}",
            params={"ref": ref},
            headers=_auth_headers(token),
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()

    content = data.get("content")
    if content:
        return base64.b64decode(content.replace("\n", ""))

    # Contents API returns null content for files > 1 MB; re-fetch via the blob SHA.
    blob_sha = data.get("sha")
    if blob_sha:
        return await fetch_blob_content(token, repo, blob_sha)

    raise ValueError(f"No content available for {path}@{ref}")
