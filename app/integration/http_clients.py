import httpx

_http_timeout = httpx.Timeout(25.0, connect=15.0)

# Shared HTTP clients for external integrations
geocoder_client = httpx.AsyncClient(timeout=_http_timeout)
ors_client = httpx.AsyncClient(timeout=_http_timeout)


async def close_http_clients() -> None:
    await geocoder_client.aclose()
    await ors_client.aclose()
