from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Sequence
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Shared backoff schedule for all HTTP embedding providers.
BACKOFF_DELAYS: Sequence[float] = (10, 20, 30, 40)
ATTEMPTS = 4

# Transient network failures worth another attempt. httpx.TimeoutException is a
# subclass of TransportError, but naming it keeps the intent obvious.
_RETRYABLE_EXCEPTIONS = (httpx.TransportError, httpx.TimeoutException)


def _delay(delays: Sequence[float], attempt: int) -> float:
    return delays[min(attempt, len(delays) - 1)]


async def post_with_retry(
    client: httpx.AsyncClient,
    url: str,
    body: dict,
    *,
    provider: str,
    attempts: int = ATTEMPTS,
    delays: Sequence[float] = BACKOFF_DELAYS,
) -> httpx.Response:
    """POST `body` to `url`, retrying rate limits, 5xx and transport errors.

    429 honours a `Retry-After` header when the server sends one, otherwise it
    falls back to the fixed backoff schedule. The final response is passed
    through `raise_for_status()`, so callers only ever see a 2xx.
    """
    resp: httpx.Response | None = None
    for attempt in range(attempts):
        try:
            resp = await client.post(url, json=body)
        except _RETRYABLE_EXCEPTIONS as exc:
            if attempt == attempts - 1:
                raise
            wait = _delay(delays, attempt)
            logger.warning(
                "%s request failed (%s: %s) — retrying in %.0fs (attempt %d/%d)",
                provider,
                type(exc).__name__,
                exc,
                wait,
                attempt + 1,
                attempts,
            )
            await asyncio.sleep(wait)
            continue

        if resp.status_code == 429:
            retry_after = float(resp.headers.get("Retry-After", 0))
            wait = retry_after if retry_after > 0 else _delay(delays, attempt)
            logger.warning(
                "%s rate-limited (429) — retrying in %.0fs (attempt %d/%d)",
                provider,
                wait,
                attempt + 1,
                attempts,
            )
            await asyncio.sleep(wait)
            continue

        if resp.status_code >= 500:
            wait = _delay(delays, attempt)
            logger.warning(
                "%s server error (%d) — retrying in %.0fs (attempt %d/%d)",
                provider,
                resp.status_code,
                wait,
                attempt + 1,
                attempts,
            )
            await asyncio.sleep(wait)
            continue

        break

    assert resp is not None  # a transport error on the last attempt re-raises
    if resp.status_code >= 400:
        logger.error("%s API error %d: %s", provider, resp.status_code, resp.text[:500])
    resp.raise_for_status()
    return resp


async def embed_in_batches(
    texts: list[str],
    *,
    client: httpx.AsyncClient,
    url: str,
    provider: str,
    batch_size: int,
    make_body: Callable[[list[str]], dict],
    extract: Callable[[Any], list[list[float]]],
    attempts: int = ATTEMPTS,
    delays: Sequence[float] = BACKOFF_DELAYS,
) -> list[list[float]]:
    """Embed `texts` in chunks of `batch_size`, one retrying POST per chunk.

    `make_body` builds the provider-specific request payload for a chunk and
    `extract` pulls the vectors out of the decoded response.
    """
    if not texts:
        return []
    all_vectors: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        resp = await post_with_retry(
            client,
            url,
            make_body(batch),
            provider=provider,
            attempts=attempts,
            delays=delays,
        )
        batch_vectors = extract(resp.json())
        if len(batch_vectors) != len(batch):
            raise ValueError(
                f"{provider} returned {len(batch_vectors)} vectors for "
                f"{len(batch)} inputs — response may be malformed"
            )
        all_vectors.extend(batch_vectors)
    return all_vectors
