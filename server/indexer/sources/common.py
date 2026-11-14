from __future__ import annotations

import asyncio
import fnmatch
import logging
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import replace

import httpx

from server.indexer.sources.base import CommitFile, SourceCommit, SourceFile
from server.parser.registry import is_supported_path

logger = logging.getLogger(__name__)

# Attempts per GET, shared by rate limits, 5xx and transport errors.
ATTEMPTS = 3
# Backoff for 5xx and transport errors. Rate limits ignore this and wait for the
# window named by the provider instead.
BACKOFF_DELAYS = (1.0, 5.0)
MAX_RATE_LIMIT_WAIT = 120.0
# Transient network failures worth another attempt. httpx.TimeoutException is a
# subclass of TransportError, but naming it keeps the intent obvious.
RETRYABLE_EXCEPTIONS = (httpx.TransportError, httpx.TimeoutException)


def matches_any(path: str, patterns: list[str]) -> bool:
    for pattern in patterns:
        if fnmatch.fnmatch(path, pattern):
            return True
        if fnmatch.fnmatch(os.path.basename(path), pattern):
            return True
    return False


def filter_tree_blobs(
    blobs: list[tuple[str, str]],
    root_prefix: str | None,
    exclude: list[str],
) -> list[SourceFile]:
    """Apply the discovery filters (root prefix, supported extension, exclude) to blobs.

    *blobs* is an iterable of ``(full_path, blob_sha)`` tuples. Returns the surviving
    files with paths made relative to *root_prefix* when set.
    """
    files: list[SourceFile] = []
    for path, sha in blobs:
        if root_prefix and not path.startswith(root_prefix):
            continue
        if not is_supported_path(path):
            continue
        if exclude and matches_any(path, exclude):
            continue
        rel_path = path[len(root_prefix) :] if root_prefix else path
        files.append(SourceFile(rel_path=rel_path, blob_sha=sha))
    return files


@asynccontextmanager
async def client_ctx(
    client: httpx.AsyncClient | None,
) -> AsyncIterator[httpx.AsyncClient]:
    """Yield the provided client, or create and close a temporary one."""
    if client is not None:
        yield client
    else:
        async with httpx.AsyncClient() as c:
            yield c


async def get_with_retry(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    *,
    label: str,
    rate_limit_statuses: tuple[int, ...],
    rate_limit_wait: Callable[[httpx.Response], float],
    params: dict | None = None,
    timeout: float = 30.0,
) -> httpx.Response:
    """GET *url*, retrying rate limits, 5xx and transport errors; raise on a final failure.

    Rate limits (responses whose status is in *rate_limit_statuses*) wait for the
    window *rate_limit_wait* derives from the response (capped at 120s); 5xx and
    transport errors use a short fixed backoff, since they carry no such hint and
    usually clear immediately.
    """
    r: httpx.Response | None = None

    for attempt in range(ATTEMPTS):
        last_attempt = attempt == ATTEMPTS - 1
        try:
            r = await client.get(url, headers=headers, params=params, timeout=timeout)
        except RETRYABLE_EXCEPTIONS as exc:
            if last_attempt:
                raise
            wait = BACKOFF_DELAYS[min(attempt, len(BACKOFF_DELAYS) - 1)]
            logger.warning(
                "%s request failed (%s: %s) — retrying in %.0fs (attempt %d/%d)",
                label,
                type(exc).__name__,
                exc,
                wait,
                attempt + 1,
                ATTEMPTS,
            )
            await asyncio.sleep(wait)
            continue

        if r.status_code in rate_limit_statuses:
            if last_attempt:
                break
            wait = min(rate_limit_wait(r), MAX_RATE_LIMIT_WAIT)
            logger.warning(
                "%s rate-limited (HTTP %d) — retrying in %.0fs",
                label,
                r.status_code,
                wait,
            )
            await asyncio.sleep(wait)
            continue

        if r.status_code >= 500:
            if last_attempt:
                break
            wait = BACKOFF_DELAYS[min(attempt, len(BACKOFF_DELAYS) - 1)]
            logger.warning(
                "%s server error (%d) — retrying in %.0fs (attempt %d/%d)",
                label,
                r.status_code,
                wait,
                attempt + 1,
                ATTEMPTS,
            )
            await asyncio.sleep(wait)
            continue

        break

    assert r is not None  # a transport error on the last attempt re-raises
    r.raise_for_status()  # surfaces the final rate-limit / 5xx error
    return r


async def fetch_commits_with_diffs(
    commits: list[SourceCommit],
    fetch_detail: Callable[[str, httpx.AsyncClient], Awaitable[list[CommitFile]]],
    *,
    max_files: int,
    max_patch_chars: int,
    concurrency: int,
    client: httpx.AsyncClient | None = None,
) -> list[SourceCommit]:
    """Fetch diff details for a batch of commits in parallel, bounded by a semaphore.

    *fetch_detail* returns the changed files for one commit SHA. A commit whose diff
    cannot be fetched is returned without files so one failure never fails the batch.
    """
    sem = asyncio.Semaphore(concurrency)

    async with client_ctx(client) as shared_client:

        async def _fetch_one(commit: SourceCommit) -> SourceCommit:
            async with sem:
                try:
                    files = await fetch_detail(commit.sha, shared_client)
                except Exception as exc:  # noqa: BLE001 — skip this commit's diff on any failure, keep the batch going
                    logger.warning(
                        "Failed to fetch diff for %s: %s", commit.sha[:8], exc
                    )
                    return commit
            return replace(
                commit,
                files=[
                    replace(f, patch=f.patch[:max_patch_chars] if f.patch else f.patch)
                    for f in files[:max_files]
                ],
            )

        return list(await asyncio.gather(*[_fetch_one(commit) for commit in commits]))
