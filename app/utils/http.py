import httpx


def safe_http_error_message(r: httpx.Response) -> str:
    try:
        j = r.json()
        return j.get("message") or str(j)[:300]
    except Exception:
        return r.text[:300]
