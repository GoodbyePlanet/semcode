from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import quote

import httpx

from server.config import settings
from server.indexer.sources import common
from server.indexer.sources.base import CommitFile, SourceCommit, SourceFile

logger = logging.getLogger(__name__)

_DIFF_CONCURRENCY = 10
_PER_PAGE = 100
# Used when a 429 carries neither Retry-After nor RateLimit-Reset.
_DEFAULT_RATE_LIMIT_WAIT = 60.0


def _auth_headers(token: str) -> dict[str, str]:
    # Public projects are readable without a token, so only send the header when set.
    return {"PRIVATE-TOKEN": token} if token else {}


def _rate_limit_wait(r: httpx.Response) -> float:
    """Seconds to wait per Retry-After / RateLimit-Reset (epoch seconds), whichever is later."""
    retry_after = float(r.headers.get("Retry-After", 0))
    reset_ts = float(r.headers.get("RateLimit-Reset", 0))
    now = time.time()
    wait = max(retry_after, reset_ts - now if reset_ts > now else 0.0)
    return wait or _DEFAULT_RATE_LIMIT_WAIT


def _count_changes(diff: str) -> tuple[int, int]:
    """Count added/removed lines in a GitLab diff, which has no file header lines."""
    additions = deletions = 0
    for line in diff.splitlines():
        if line.startswith("+"):
            additions += 1
        elif line.startswith("-"):
            deletions += 1
    return additions, deletions


def _file_status(item: dict[str, Any]) -> str:
    if item.get("new_file"):
        return "added"
    if item.get("deleted_file"):
        return "deleted"
    if item.get("renamed_file"):
        return "renamed"
    return "modified"


class GitLabSource:
    """`CodeSource` backed by the GitLab REST API (v4) for a single project.

    *repo* is the project's full path (``group/subgroup/project``) or numeric ID.
    """

    def __init__(self, token: str, repo: str) -> None:
        self._token = token
        self._project_url = (
            f"{settings.gitlab_api_url.rstrip('/')}/projects/{quote(repo, safe='')}"
        )

    async def _get(
        self,
        client: httpx.AsyncClient,
        url: str,
        params: dict | None = None,
        timeout: float = 30.0,
    ) -> httpx.Response:
        return await common.get_with_retry(
            client,
            url,
            _auth_headers(self._token),
            label="GitLab",
            rate_limit_statuses=(429,),
            rate_limit_wait=_rate_limit_wait,
            params=params,
            timeout=timeout,
        )

    async def _paginate(
        self, client: httpx.AsyncClient, url: str, params: dict
    ) -> AsyncIterator[list[dict[str, Any]]]:
        """Yield each page of a list endpoint, following keyset `Link` or offset `X-Next-Page`."""
        next_url: str | None = url
        next_params: dict | None = params
        while next_url:
            r = await self._get(client, next_url, next_params)
            yield r.json()

            link = r.links.get("next")
            if link:
                next_url, next_params = (
                    link["url"],
                    None,
                )  # URL already carries the query
            elif r.headers.get("X-Next-Page"):
                next_url = url
                next_params = {**params, "page": r.headers["X-Next-Page"]}
            else:
                next_url = None

    async def list_files(
        self,
        ref: str,
        exclude: list[str],
        root: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> list[SourceFile]:
        root_prefix = root.rstrip("/") + "/" if root else None
        params: dict[str, str | int] = {
            "ref": ref,
            "recursive": "true",
            "per_page": _PER_PAGE,
            "pagination": "keyset",
        }
        if root:
            params["path"] = root.rstrip("/")

        blobs: list[tuple[str, str]] = []
        async with common.client_ctx(client) as c:
            async for page in self._paginate(
                c, f"{self._project_url}/repository/tree", params
            ):
                blobs.extend((i["path"], i["id"]) for i in page if i["type"] == "blob")

        return common.filter_tree_blobs(blobs, root_prefix, exclude)

    async def fetch_blob(
        self, blob_sha: str, client: httpx.AsyncClient | None = None
    ) -> bytes:
        async with common.client_ctx(client) as c:
            r = await self._get(
                c,
                f"{self._project_url}/repository/blobs/{blob_sha}/raw",
                timeout=60,
            )
        return r.content

    async def fetch_file(self, path: str, ref: str) -> bytes:
        async with httpx.AsyncClient() as c:
            r = await self._get(
                c,
                f"{self._project_url}/repository/files/{quote(path, safe='')}/raw",
                {"ref": ref},
            )
        return r.content

    async def list_commits(
        self,
        ref: str,
        root: str | None = None,
        max_commits: int = 500,
        client: httpx.AsyncClient | None = None,
    ) -> list[SourceCommit]:
        params: dict[str, str | int] = {"ref_name": ref, "per_page": _PER_PAGE}
        if root:
            params["path"] = root

        commits: list[SourceCommit] = []
        async with common.client_ctx(client) as c:
            async for page in self._paginate(
                c, f"{self._project_url}/repository/commits", params
            ):
                commits.extend(
                    SourceCommit(
                        sha=item["id"],
                        message=item["message"],
                        author_name=item["author_name"],
                        author_email=item["author_email"],
                        committed_at=item["authored_date"],
                    )
                    for item in page
                )
                if len(commits) >= max_commits:
                    break
        return commits[:max_commits]

    async def _fetch_commit_detail(
        self, sha: str, client: httpx.AsyncClient
    ) -> list[CommitFile]:
        files: list[CommitFile] = []
        async for page in self._paginate(
            client,
            f"{self._project_url}/repository/commits/{sha}/diff",
            {"per_page": _PER_PAGE},
        ):
            for item in page:
                # Oversized diffs come back with an empty body (or are flagged); no patch.
                diff = item.get("diff") or ""
                additions, deletions = _count_changes(diff)
                files.append(
                    CommitFile(
                        filename=item["new_path"],
                        status=_file_status(item),
                        additions=additions,
                        deletions=deletions,
                        patch=diff or None,
                    )
                )
        return files

    async def fetch_commits_with_diffs(
        self,
        commits: list[SourceCommit],
        max_files: int = 50,
        max_patch_chars: int = 2000,
        client: httpx.AsyncClient | None = None,
    ) -> list[SourceCommit]:
        return await common.fetch_commits_with_diffs(
            commits,
            self._fetch_commit_detail,
            max_files=max_files,
            max_patch_chars=max_patch_chars,
            concurrency=_DIFF_CONCURRENCY,
            client=client,
        )
