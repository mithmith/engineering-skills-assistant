from typing import List

from app.api.schemas import StepOut
from app.config import logger


def fmt_distance_m(m: float) -> str:
    if m < 950:
        return f"{int(round(m))} м"
    return f"{m/1000:.1f} км".replace(".", ",")


def fmt_duration_s(s: float) -> str:
    s = int(round(s))
    h = s // 3600
    m = (s % 3600) // 60
    if h and m:
        return f"{h} ч {m} мин"
    if h:
        return f"{h} ч"
    if m:
        return f"{m} мин"
    return f"{s} с"


def build_markdown(
    a_label: str,
    a_lat: float,
    a_lon: float,
    b_label: str,
    b_lat: float,
    b_lon: float,
    steps: List[StepOut],
    total_m: float,
    total_s: float,
) -> str:
    logger.debug(
        "Building markdown: A=(%s,%s '%s') B=(%s,%s '%s') steps=%d",
        a_lat,
        a_lon,
        a_label,
        b_lat,
        b_lon,
        b_label,
        len(steps),
    )
    md = []
    md.append("# Маршрут A → B\n")
    md.append(f"**A:** {a_label} ({a_lat:.6f}, {a_lon:.6f})  \n**B:** {b_label} ({b_lat:.6f}, {b_lon:.6f})\n")
    md.append(f"**Итого:** {fmt_distance_m(total_m)} • {fmt_duration_s(total_s)}\n")

    md.append("## По населённым пунктам\n")
    cur_loc = None
    buf: List[StepOut] = []

    def flush():
        nonlocal buf
        if not buf:
            return
        loc = cur_loc or "Между населёнными пунктами"
        md.append(f"### {loc}\n")
        for s in buf:
            instr = s.instruction or ""
            street = s.street or "без названия"
            md.append(
                f"- {instr} — **{street}** — {fmt_distance_m(s.distance_m)} • {fmt_duration_s(s.duration_s)}  \n"
                f"  координаты: ({s.start_lat:.6f}, {s.start_lon:.6f})"
            )
            if s.via_localities:
                for v in s.via_localities:
                    md.append(f"  - через: **{v.name}** ({v.lat:.6f}, {v.lon:.6f})")
        md.append("")
        buf = []

    for s in steps:
        if s.locality != cur_loc:
            flush()
            cur_loc = s.locality
        buf.append(s)
    flush()

    md.append("## Ключевые точки\n")
    for s in steps:
        md.append(f"- Шаг {s.idx+1}: ({s.start_lat:.6f}, {s.start_lon:.6f}) — {s.street or 'улица не определена'}")

    return "\n".join(md)
