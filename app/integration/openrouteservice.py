from typing import Optional

from fastapi import HTTPException

from app.api.schemas import OptionsIn
from app.config import logger, settings
from app.integration.http_clients import ors_client
from app.utils.http import safe_http_error_message


async def ors_route(
    a_lat: float,
    a_lon: float,
    b_lat: float,
    b_lon: float,
    opt: Optional[OptionsIn] = None,
) -> dict:
    if opt is None:
        opt = OptionsIn()
    logger.debug("Requesting ORS: A=(%s,%s) B=(%s,%s) opts=%s", a_lat, a_lon, b_lat, b_lon, opt)
    headers = {"Authorization": settings.ors_api_key, "Content-Type": "application/json"}
    body = {
        "coordinates": [[a_lon, a_lat], [b_lon, b_lat]],  # ORS: [lon, lat]
        "language": opt.language,
        "units": "m",
        "instructions": True,
    }
    if opt.avoid_tolls:
        body["options"] = {"avoid_features": ["tollways"]}

    r = await ors_client.post(settings.ors_directions_url, headers=headers, json=body)
    if r.status_code != 200:
        raise HTTPException(502, f"ORS HTTP {r.status_code}: {safe_http_error_message(r)}")
    logger.debug("ORS HTTP %s", r.status_code)
    return r.json()
