from __future__ import annotations

import httpx

from server.indexer import github_source as gh
from server.indexer.sources.base import SourceCommit, SourceFile


class GitHubSource:
    """`CodeSource` backed by the GitHub REST API for a single repository."""

    def __init__(self, token: str, repo: str) -> None:
        self._token = token
        self._repo = repo

    async def list_files(
        self,
        ref: str,
        exclude: list[str],
        root: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> list[SourceFile]:
        return await gh.list_github_files(
            self._token, self._repo, ref, "", exclude, root, client=client
        )

    async def fetch_blob(
        self, blob_sha: str, client: httpx.AsyncClient | None = None
    ) -> bytes:
        return await gh.fetch_blob_content(
            self._token, self._repo, blob_sha, client=client
        )

    async def fetch_file(self, path: str, ref: str) -> bytes:
        return await gh.fetch_file_content(self._token, self._repo, path, ref)

    async def list_commits(
        self,
        ref: str,
        root: str | None = None,
        max_commits: int = 500,
        client: httpx.AsyncClient | None = None,
    ) -> list[SourceCommit]:
        return await gh.list_commits(
            self._token,
            self._repo,
            ref,
            root=root,
            max_commits=max_commits,
            client=client,
        )

    async def fetch_commits_with_diffs(
        self,
        commits: list[SourceCommit],
        max_files: int = 50,
        max_patch_chars: int = 2000,
        client: httpx.AsyncClient | None = None,
    ) -> list[SourceCommit]:
        return await gh.fetch_commits_with_diffs(
            self._token,
            self._repo,
            commits,
            max_files=max_files,
            max_patch_chars=max_patch_chars,
            client=client,
        )
