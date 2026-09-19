import asyncio

import httpx
import sentry_sdk


async def request(client: httpx.AsyncClient, method: str, url: str, **kwargs) -> httpx.Response:
    """At most one retry; enclosing pipeline deadlines also bound this helper."""
    for attempt in range(2):
        try:
            response = await client.request(method, url, **kwargs)
            response.raise_for_status()
            return response
        except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as exc:
            transient = not isinstance(exc, httpx.HTTPStatusError) or exc.response.status_code in {
                408, 429, 500, 502, 503, 504,
            }
            if attempt or not transient:
                raise
            with sentry_sdk.start_span(op="upstream.retry", name="transient upstream retry"):
                await asyncio.sleep(0.25)
    raise AssertionError("unreachable")
