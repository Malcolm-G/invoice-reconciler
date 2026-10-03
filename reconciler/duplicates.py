"""Duplicate detection from the RAW rows with code-only normalisation (no Claude involved).

Two rows are duplicates only if every detail matches after normalisation. The
first occurrence is kept; later ones are excluded. Same flight on another day
is a different date, so it is a different job.
"""
from datetime import date

from reconciler.normalise import Mappings, hhmm, leg_of, parse_date, parse_time, service_of, _key


def row_key(raw: dict, maps: Mappings, period_start: date, period_end: date) -> tuple:
    d, _ = parse_date(raw.get("Date"), period_start, period_end)
    service = service_of(maps, raw.get("Service")) or _key(raw.get("Service"))
    return (
        d.isoformat() if d else _key(raw.get("Date")),
        _key(raw.get("Flight")),
        _key(raw.get("Aircraft")),
        leg_of(maps, raw.get("Transit/Term")) if _key(raw.get("Transit/Term")) in maps.legs
        else _key(raw.get("Transit/Term")),
        service,
        hhmm(parse_time(raw.get("Start"))) or _key(raw.get("Start")),
        hhmm(parse_time(raw.get("End"))) or _key(raw.get("End")),
        _key(raw.get("Notes")),
    )


def find_duplicates(rows: list[dict], maps: Mappings, period_start: date, period_end: date) -> dict[int, int]:
    """Map duplicate row_id -> row_id of the first matching row."""
    seen: dict[tuple, int] = {}
    dups: dict[int, int] = {}
    for r in rows:
        k = row_key(r, maps, period_start, period_end)
        if k in seen:
            dups[r["row_id"]] = seen[k]
        else:
            seen[k] = r["row_id"]
    return dups
