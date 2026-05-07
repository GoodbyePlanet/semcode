from __future__ import annotations

import asyncio
import base64
import fnmatch
import logging
import os
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

import httpx

from server.parser.registry import is_supported_path

_GITHUB_API = "https://api.github.com"
_DIFF_CONCURRENCY = 10

logger = logging.getLogger(__name__)


@dataclass
class GitHubFile:
    rel_path: str  # path within the repo, e.g. "src/main/java/Foo.java"
    blob_sha: str  # git blob SHA — used as file_hash for incremental indexing


@dataclass
class CommitFile:
    filename: str
    status: str  # "added" | "modified" | "deleted" | "renamed"
    additions: int
    deletions: int
    patch: str | None


@dataclass
class GitHubCommit:
    sha: str
    message: str
    author_name: str
    author_email: str
    committed_at: str  # ISO 8601
    files: list[CommitFile] = field(default_factory=list)


def _matches_any(path: str, patterns: list[str]) -> bool:
    for pattern in patterns:
        if fnmatch.fnmatch(path, pattern):
            return True
        if fnmatch.fnmatch(os.path.basename(path), pattern):
            return True
    return False


def _auth_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


@asynccontextmanager
async def _client_ctx(
    client: httpx.AsyncClient | None,
) -> AsyncIterator[httpx.AsyncClient]:
    """Yield the provided client, or create and close a temporary one."""
    if client is not None:
        yield client
    else:
        async with httpx.AsyncClient() as c:
            yield c


async def _gh_get(
    client: httpx.AsyncClient,
    url: str,
    token: str,
    params: dict | None = None,
    timeout: float = 30.0,
) -> Any:
    """GET a GitHub API URL, retrying up to 3 times on rate-limit responses (403/429)."""
    headers = _auth_headers(token)
    for _ in range(3):
        r = await client.get(url, headers=headers, params=params, timeout=timeout)
        if r.status_code not in (403, 429):
            r.raise_for_status()
            return r.json()
        reset_ts = float(r.headers.get("X-RateLimit-Reset", 0))
        retry_after = float(r.headers.get("Retry-After", 60))
        now = time.time()
        wait = min(max(retry_after, reset_ts - now if reset_ts > now else 0.0), 120.0)
        logger.warning(
            "GitHub rate-limited (HTTP %d) — retrying in %.0fs", r.status_code, wait
        )
        await asyncio.sleep(wait)
    r.raise_for_status()  # raise final rate-limit error after exhausting retries
    return r.json()  # unreachable


async def list_github_files(
    token: str,
    repo: str,
    ref: str,
    service_name: str,
    exclude: list[str],
    root: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> list[GitHubFile]:
    """List matching files via the git trees API (single request for the full tree).

    All files whose extension or basename is recognised by the parser registry are
    indexed. If *root* is set, only files under that path prefix are considered.
    Paths matching *exclude* patterns are skipped.
    """
    async with _client_ctx(client) as c:
        tree = await _gh_get(
            c,
            f"{_GITHUB_API}/repos/{repo}/git/trees/{ref}",
            token,
            {"recursive": "1"},
            timeout=30,
        )

    if tree.get("truncated"):
        logger.warning(
            "GitHub trees response truncated for %s@%s — repo is very large; "
            "some files may be missing from the index.",
            repo,
            ref,
        )

    root_prefix = root.rstrip("/") + "/" if root else None

    files: list[GitHubFile] = []
    for item in tree.get("tree", []):
        if item["type"] != "blob":
            continue
        path = item["path"]
        if root_prefix and not path.startswith(root_prefix):
            continue
        if not is_supported_path(path):
            continue
        if exclude and _matches_any(path, exclude):
            continue
        rel_path = path[len(root_prefix) :] if root_prefix else path
        files.append(
            GitHubFile(
                rel_path=rel_path,
                blob_sha=item["sha"],
            )
        )
    return files


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
                c, f"{_GITHUB_API}/repos/{repo}/commits", token, params
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
            c, f"{_GITHUB_API}/repos/{repo}/commits/{sha}", token, timeout=30
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
) -> list[GitHubCommit]:
    """Fetch diff details for a batch of commits in parallel, bounded by a semaphore."""
    sem = asyncio.Semaphore(_DIFF_CONCURRENCY)

    async with httpx.AsyncClient() as shared_client:

        async def _fetch_one(commit: GitHubCommit) -> GitHubCommit:
            async with sem:
                try:
                    files = await fetch_commit_detail(
                        token, repo, commit.sha, client=shared_client
                    )
                except Exception as exc:
                    logger.warning(
                        "Failed to fetch diff for %s: %s", commit.sha[:8], exc
                    )
                    return commit
            truncated = []
            for f in files[:max_files]:
                patch = f.patch
                if patch and len(patch) > max_patch_chars:
                    patch = patch[:max_patch_chars]
                truncated.append(
                    CommitFile(
                        filename=f.filename,
                        status=f.status,
                        additions=f.additions,
                        deletions=f.deletions,
                        patch=patch,
                    )
                )
            return GitHubCommit(
                sha=commit.sha,
                message=commit.message,
                author_name=commit.author_name,
                author_email=commit.author_email,
                committed_at=commit.committed_at,
                files=truncated,
            )

        return list(await asyncio.gather(*[_fetch_one(commit) for commit in commits]))


async def fetch_blob_content(
    token: str,
    repo: str,
    blob_sha: str,
    client: httpx.AsyncClient | None = None,
) -> bytes:
    """Fetch file content by git blob SHA. Used during indexing — avoids re-resolving paths."""
    async with _client_ctx(client) as c:
        data = await _gh_get(
            c, f"{_GITHUB_API}/repos/{repo}/git/blobs/{blob_sha}", token, timeout=60
        )
    return base64.b64decode(data["content"].replace("\n", ""))


async def fetch_file_content(token: str, repo: str, path: str, ref: str) -> bytes:
    """Fetch file content by path and ref. Falls back to blob API for files > 1 MB."""
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{_GITHUB_API}/repos/{repo}/contents/{path}",
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
