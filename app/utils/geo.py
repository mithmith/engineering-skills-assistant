import math
from typing import List, Tuple
from app.config import logger


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = phi2 - phi1
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _interp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def round6(x: float) -> float:
    return float(f"{x:.6f}")


def sample_points_along(
    coords_lonlat: List[List[float]], interval_m: float, max_points: int = 10
) -> List[Tuple[float, float]]:
    logger.debug("Sampling points along geometry: n_coords=%d interval_m=%s max_points=%d", len(coords_lonlat), interval_m, max_points)
    if len(coords_lonlat) < 2:
        return []
    seg_len: List[float] = []
    total = 0.0
    for i in range(len(coords_lonlat) - 1):
        lon1, lat1 = coords_lonlat[i]
        lon2, lat2 = coords_lonlat[i + 1]
        d = haversine_m(lat1, lon1, lat2, lon2)
        seg_len.append(d)
        total += d
    if total < interval_m:
        return []

    targets = []
    k = 1
    while k * interval_m < total and len(targets) < max_points:
        targets.append(k * interval_m)
        k += 1

    pts: List[Tuple[float, float]] = []
    acc = 0.0
    seg_idx = 0
    for tdist in targets:
        while seg_idx < len(seg_len) and acc + seg_len[seg_idx] < tdist:
            acc += seg_len[seg_idx]
            seg_idx += 1
        if seg_idx >= len(seg_len):
            break
        remain = tdist - acc
        frac = 0.0 if seg_len[seg_idx] == 0 else (remain / seg_len[seg_idx])
        lon1, lat1 = coords_lonlat[seg_idx]
        lon2, lat2 = coords_lonlat[seg_idx + 1]
        lat = _interp(lat1, lat2, frac)
        lon = _interp(lon1, lon2, frac)
        pts.append((round6(lat), round6(lon)))
    logger.debug("Sampled %d points", len(pts))
    return pts
