from __future__ import annotations

import base64
import fnmatch
import os
from dataclasses import dataclass

import httpx

_GITHUB_API = "https://api.github.com"

_EXT_TO_LANGUAGE = {
    ".go": "go",
    ".java": "java",
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "typescript",
    ".jsx": "typescript",
}


@dataclass
class GitHubFile:
    rel_path: str    # path within the repo, e.g. "src/main/java/Foo.java"
    service_name: str
    language: str
    blob_sha: str    # git blob SHA — used as file_hash for incremental indexing


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


async def list_github_files(
    token: str,
    repo: str,
    ref: str,
    service_name: str,
    languages: list[str],
    include: list[str],
    exclude: list[str],
) -> list[GitHubFile]:
    """List matching files via the git trees API (single request for the full tree)."""
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{_GITHUB_API}/repos/{repo}/git/trees/{ref}",
            params={"recursive": "1"},
            headers=_auth_headers(token),
            timeout=30,
        )
        r.raise_for_status()
        tree = r.json()

    files: list[GitHubFile] = []
    for item in tree.get("tree", []):
        if item["type"] != "blob":
            continue
        path = item["path"]
        ext = os.path.splitext(path)[1]
        language = _EXT_TO_LANGUAGE.get(ext)
        if language is None or language not in languages:
            continue
        if include and not _matches_any(path, include):
            continue
        if exclude and _matches_any(path, exclude):
            continue
        files.append(GitHubFile(
            rel_path=path,
            service_name=service_name,
            language=language,
            blob_sha=item["sha"],
        ))
    return files


async def fetch_blob_content(token: str, repo: str, blob_sha: str) -> bytes:
    """Fetch file content by git blob SHA. Used during indexing — avoids re-resolving paths."""
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{_GITHUB_API}/repos/{repo}/git/blobs/{blob_sha}",
            headers=_auth_headers(token),
            timeout=60,
        )
        r.raise_for_status()
        data = r.json()
        return base64.b64decode(data["content"].replace("\n", ""))


async def fetch_file_content(token: str, repo: str, path: str, ref: str) -> bytes:
    """Fetch file content by path and ref. Used by get_code_context for current file version."""
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{_GITHUB_API}/repos/{repo}/contents/{path}",
            params={"ref": ref},
            headers=_auth_headers(token),
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        return base64.b64decode(data["content"].replace("\n", ""))
