import asyncio
from typing import Dict, List, Optional, Tuple

from fastapi import HTTPException

from app.api.schemas import OptionsIn, PointIn, StepOut, ViaLocality
from app.integration.openrouteservice import ors_route
from app.integration.yandex_geocoder import geocode_forward, geocode_reverse
from app.utils.geo import round6, sample_points_along
from app.config import logger


def ors_extract_steps(
    data: dict,
) -> Tuple[List[StepOut], float, float, List[List[float]], List[Tuple[int, int]]]:
    logger.debug("Extracting steps from ORS response")
    features = data.get("features") or []
    if not features:
        logger.info("ORS: empty features")
        raise HTTPException(422, "ORS: маршрут не найден (пустой features)")
    feat = features[0]
    props = feat.get("properties", {}) or {}
    summary = props.get("summary", {}) or {}
    total_m = float(summary.get("distance", 0.0))
    total_s = float(summary.get("duration", 0.0))

    coords = (feat.get("geometry") or {}).get("coordinates") or []

    out: List[StepOut] = []
    bounds: List[Tuple[int, int]] = []
    idx = 0
    for seg in props.get("segments", []) or []:
        for st in seg.get("steps", []) or []:
            wp = st.get("way_points", [0, 0])
            i0, i1 = int(wp[0]), int(wp[1])
            lon, lat = coords[i0]
            out.append(
                StepOut(
                    idx=idx,
                    start_lat=round6(float(lat)),
                    start_lon=round6(float(lon)),
                    distance_m=int(round(float(st.get("distance", 0)))),
                    duration_s=int(round(float(st.get("duration", 0)))),
                    instruction=st.get("instruction"),
                    street=(st.get("name") or None),
                    locality=None,
                )
            )
            bounds.append((i0, i1))
            idx += 1

    logger.debug("Extracted steps=%d total_m=%s total_s=%s", len(out), total_m, total_s)
    return out, total_m, total_s, coords, bounds


async def annotate_intermediate_localities(
    steps: List[StepOut],
    step_bounds: List[Tuple[int, int]],
    coords: List[List[float]],
    *,
    min_step_m: int = 5000,
    sample_interval_m: int = 5000,
) -> None:
    logger.debug("Annotating intermediate localities")
    sample_tasks = []
    sample_meta: List[Tuple[int, float, float]] = []

    for i, s in enumerate(steps):
        if s.distance_m <= min_step_m:
            continue
        i0, i1 = step_bounds[i]
        sub = coords[i0 : i1 + 1]
        pts = sample_points_along(sub, interval_m=sample_interval_m, max_points=10)
        for lat, lon in pts:
            sample_meta.append((i, lat, lon))
            sample_tasks.append(geocode_reverse(lat, lon, kind="locality"))

    if not sample_tasks:
        logger.debug("No long steps to annotate")
        return

    results = await asyncio.gather(*sample_tasks, return_exceptions=True)

    by_step: Dict[int, List[ViaLocality]] = {}
    for (i, lat, lon), res in zip(sample_meta, results):
        if isinstance(res, Exception) or not isinstance(res, dict):
            continue
        name = res.get("locality") or res.get("province")
        if not name:
            continue
        if i not in by_step:
            by_step[i] = []
        if not by_step[i] or by_step[i][-1].name != name:
            by_step[i].append(ViaLocality(name=name, lat=round6(lat), lon=round6(lon)))

    for i, s in enumerate(steps):
        vias = by_step.get(i, [])
        if s.locality:
            vias = [v for v in vias if v.name != s.locality]
        s.via_localities = vias or None
    logger.debug("Annotated intermediate localities where applicable")


async def enrich_localities_with_yandex(steps: List[StepOut]) -> None:
    logger.debug("Enriching steps with locality via Yandex reverse geocode")
    tasks = []
    for s in steps:
        lat, lon = s.start_lat, s.start_lon
        if lat == 0.0 and lon == 0.0:
            tasks.append(asyncio.sleep(0, result={}))
        else:
            tasks.append(geocode_reverse(lat, lon, kind="locality"))

    results = await asyncio.gather(*tasks, return_exceptions=True)
    for s, res in zip(steps, results):
        if isinstance(res, Exception) or not isinstance(res, dict):
            continue
        s.locality = res.get("locality") or res.get("province") or None
    logger.debug("Enriched steps with locality")


async def ensure_coords(p: PointIn) -> Tuple[float, float, str]:
    logger.debug("Ensuring coords for point: %s", p)
    if p.lat is not None and p.lon is not None:
        return float(p.lat), float(p.lon), f"{p.lat:.6f}, {p.lon:.6f}"
    lat, lon = await geocode_forward(p.address)
    return lat, lon, p.address
