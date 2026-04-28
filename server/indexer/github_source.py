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
    ".md": "markdown",
    ".json": "json",
    ".html": "html",
    ".htm": "html",
    ".css": "css",
}

# Exact basename that map to a language regardless of extension
_FILENAME_TO_LANGUAGE = {
    "Dockerfile": "dockerfile",
    "dockerfile": "dockerfile",
    "docker-compose.yml": "docker-compose",
    "docker-compose.yaml": "docker-compose",
    "compose.yml": "docker-compose",
    "compose.yaml": "docker-compose",
}


@dataclass
class GitHubFile:
    rel_path: str    # path within the repo, e.g. "src/main/java/Foo.java"
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
    exclude: list[str],
    root: str | None = None,
) -> list[GitHubFile]:
    """List matching files via the git trees API (single request for the full tree).

    All files whose extension or basename is recognised by the parser registry are
    indexed. If *root* is set, only files under that path prefix are considered.
    Paths matching *exclude* patterns are skipped.
    """
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{_GITHUB_API}/repos/{repo}/git/trees/{ref}",
            params={"recursive": "1"},
            headers=_auth_headers(token),
            timeout=30,
        )
        r.raise_for_status()
        tree = r.json()

    root_prefix = root.rstrip("/") + "/" if root else None

    files: list[GitHubFile] = []
    for item in tree.get("tree", []):
        if item["type"] != "blob":
            continue
        path = item["path"]
        if root_prefix and not path.startswith(root_prefix):
            continue
        basename = os.path.basename(path)
        ext = os.path.splitext(path)[1]
        # Exact filename match wins over extension (e.g. Dockerfile, docker-compose.yml)
        language = _FILENAME_TO_LANGUAGE.get(basename) or _EXT_TO_LANGUAGE.get(ext)
        if language is None:
            continue
        if exclude and _matches_any(path, exclude):
            continue
        files.append(GitHubFile(
            rel_path=path,
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
