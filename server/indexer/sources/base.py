from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

import httpx


@dataclass
class SourceFile:
    rel_path: str  # path within the repo (relative to the service root)
    blob_sha: str  # git blob SHA — used as file_hash for incremental indexing


@dataclass
class CommitFile:
    filename: str
    status: str  # "added" | "modified" | "deleted" | "renamed"
    additions: int
    deletions: int
    patch: str | None


@dataclass
class SourceCommit:
    sha: str
    message: str
    author_name: str
    author_email: str
    committed_at: str  # ISO 8601
    files: list[CommitFile] = field(default_factory=list)


@runtime_checkable
class CodeSource(Protocol):
    """A git hosting provider the indexer can read code and history from.

    Implementations are bound to one repository (and its credentials).
    """

    async def list_files(
        self,
        ref: str,
        exclude: list[str],
        root: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> list[SourceFile]: ...

    async def fetch_blob(
        self, blob_sha: str, client: httpx.AsyncClient | None = None
    ) -> bytes: ...

    async def fetch_file(self, path: str, ref: str) -> bytes: ...

    async def list_commits(
        self,
        ref: str,
        root: str | None = None,
        max_commits: int = 500,
        client: httpx.AsyncClient | None = None,
    ) -> list[SourceCommit]: ...

    async def fetch_commits_with_diffs(
        self,
        commits: list[SourceCommit],
        max_files: int = 50,
        max_patch_chars: int = 2000,
        client: httpx.AsyncClient | None = None,
    ) -> list[SourceCommit]: ...
