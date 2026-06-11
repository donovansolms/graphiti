"""
Copyright 2024, Zep Software, Inc.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

import asyncio
import http.cookiejar
import logging

import httpx

logger = logging.getLogger(__name__)

# Mirror the OpenAI SDK's own httpx defaults so the only behavioural change
# introduced by swapping in our client is 431-retry + cookie handling.
# (openai._constants.DEFAULT_TIMEOUT / DEFAULT_CONNECTION_LIMITS)
_DEFAULT_TIMEOUT = httpx.Timeout(timeout=600.0, connect=5.0)
_DEFAULT_LIMITS = httpx.Limits(max_connections=1000, max_keepalive_connections=100)

# OpenAI's Cloudflare edge intermittently returns 431 ("request headers too
# large") under concurrent load even for tiny (<1KB) header sets — it is a
# spurious edge error, not a real header-size problem (reproduced: byte-identical
# requests, most succeed, a few 431). The OpenAI SDK retries 408/409/429/5xx but
# NOT 431, so a single spurious 431 fails the whole call. We retry it at the
# transport layer so every request through this client (embeddings, chat, rerank)
# transparently survives the blip.
_RETRY_STATUS = 431
_MAX_RETRIES = 3  # bounded: at most 3 retries (4 attempts total), never unbounded
_BACKOFF_BASE_SECONDS = 0.15


class _RejectAllCookiePolicy(http.cookiejar.DefaultCookiePolicy):
    """Cookie policy that refuses to store or return any cookie.

    A long-lived OpenAI client otherwise accumulates Cloudflare ``__cf_bm`` /
    ``_cfuvid`` cookies in its jar and replays them as a growing ``Cookie``
    header. This is harmless hygiene only — it is NOT the cause of the 431s
    (those fire with an empty jar) — but it keeps the header set minimal.
    """

    def set_ok(self, cookie, request):
        return False

    def return_ok(self, cookie, request):
        return False


class _Retry431Transport(httpx.AsyncBaseTransport):
    """Wrap a transport and retry the spurious Cloudflare 431 up to _MAX_RETRIES
    times with linear backoff. Any other status (success or a real error) is
    returned immediately, and an exhausted retry budget returns the final 431 so
    behaviour degrades to exactly what the SDK would have seen otherwise."""

    def __init__(self, inner: httpx.AsyncBaseTransport):
        self._inner = inner

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await self._inner.handle_async_request(request)
        attempt = 0
        while response.status_code == _RETRY_STATUS and attempt < _MAX_RETRIES:
            logger.warning(
                'spurious %s from OpenAI edge on %s %s; retrying (%d/%d)',
                response.status_code,
                request.method,
                request.url,
                attempt + 1,
                _MAX_RETRIES,
            )
            # Drain + close the (tiny) 431 body so the connection is released
            # before we resend. The request body is plain bytes, so it replays.
            await response.aread()
            await response.aclose()
            await asyncio.sleep(_BACKOFF_BASE_SECONDS * (attempt + 1))
            attempt += 1
            response = await self._inner.handle_async_request(request)
        if attempt and response.status_code != _RETRY_STATUS:
            logger.warning('recovered after %d retr%s', attempt, 'y' if attempt == 1 else 'ies')
        elif attempt:
            logger.error('still %s after %d retries; giving up', response.status_code, attempt)
        return response

    async def aclose(self) -> None:
        await self._inner.aclose()


def create_resilient_http_client() -> httpx.AsyncClient:
    """Build an ``httpx.AsyncClient`` hardened against OpenAI edge flakiness.

    - Retries the spurious Cloudflare ``431`` up to ``_MAX_RETRIES`` times (the
      OpenAI SDK won't retry 431 on its own).
    - Drops cookies so a long-lived client never accumulates them.
    - Matches the OpenAI SDK's default timeout / connection limits, so nothing
      else about request behaviour changes.
    """
    # Limits live on the transport; the 431-retry wrapper sits in front of it.
    transport = _Retry431Transport(httpx.AsyncHTTPTransport(limits=_DEFAULT_LIMITS))
    client = httpx.AsyncClient(
        transport=transport,
        timeout=_DEFAULT_TIMEOUT,
        follow_redirects=True,
    )
    client.cookies.jar.set_policy(_RejectAllCookiePolicy())
    return client
