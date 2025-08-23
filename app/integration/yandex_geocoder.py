import asyncio
from typing import Dict, Optional, Tuple

from fastapi import HTTPException

from app.config import settings, logger
from app.integration.http_clients import geocoder_client
from app.utils.http import safe_http_error_message

_rev_sem = asyncio.Semaphore(settings.rev_geocoder_concurrency)


async def geocode_forward(address: str) -> Tuple[float, float]:
    params = {
        "apikey": settings.yandex_geocoder_api_key,
        "geocode": address,
        "lang": "ru_RU",
        "results": 1,
        "format": "json",
    }
    logger.debug("Yandex forward geocode: %s", address)
    r = await geocoder_client.get(settings.yandex_geocoder_url, params=params)
    if r.status_code != 200:
        _msg = safe_http_error_message(r)
        logger.info("Yandex forward geocode HTTP %s: %s", r.status_code, _msg)
        raise HTTPException(r.status_code, f"Geocoder forward error: {_msg}")

    data = r.json()
    try:
        member = data["response"]["GeoObjectCollection"]["featureMember"][0]["GeoObject"]
        pos = member["Point"]["pos"]  # "lon lat"
        lon_str, lat_str = pos.split()
        return float(lat_str), float(lon_str)
    except Exception:
        pass

    try:
        feat = data["features"][0]
        lon, lat = feat["geometry"]["coordinates"]
        return float(lat), float(lon)
    except Exception as e:
        logger.info("Yandex forward geocode failed to parse response: %s", e)
        raise HTTPException(422, f"Не удалось геокодировать адрес: {address!r}. Детали: {e}")


async def geocode_reverse(lat: float, lon: float, kind: Optional[str] = None) -> Dict[str, str]:
    params = {
        "apikey": settings.yandex_geocoder_api_key,
        "geocode": f"{lat},{lon}",
        "sco": "latlong",
        "lang": "ru_RU",
        "results": 1,
        "format": "json",
    }
    if kind:
        params["kind"] = kind

    async with _rev_sem:
        r = await geocoder_client.get(settings.yandex_geocoder_url, params=params)

    if r.status_code != 200:
        logger.info("Yandex reverse geocode HTTP %s", r.status_code)
        return {}

    data = r.json()
    try:
        member = data["response"]["GeoObjectCollection"]["featureMember"][0]["GeoObject"]
        addr = member["metaDataProperty"]["GeocoderMetaData"]["Address"]
        comps = {c["kind"]: c["name"] for c in addr.get("Components", [])}
        name = member.get("name")
        full_text = addr.get("formatted")
        out = {"name": name, "full": full_text}
        out.update(comps)
        return out
    except Exception:
        pass

    try:
        feat = data["features"][0]
        props = feat.get("properties", {})
        comps_list = props.get("Components", []) or props.get("Address", {}).get("Components", [])
        comps = {c.get("kind"): c.get("name") for c in comps_list if c.get("kind") and c.get("name")}
        name = props.get("name")
        descr = props.get("description")
        out = {"name": name, "full": descr}
        out.update(comps)
        return out
    except Exception:
        logger.debug("Yandex reverse geocode: no components found")
        return {}
