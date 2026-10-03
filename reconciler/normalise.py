"""Trivial, documented normalisation rules. Plain code, no Claude.

Dates are read as DD/MM (see README). Times are strict: anything that could be
misread is returned as None (unparseable) rather than guessed.
"""
import csv
import re
from dataclasses import dataclass
from datetime import date

import config

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


# ---------- mapping tables (visible CSVs in data/mappings) ----------

@dataclass(frozen=True)
class Mappings:
    aircraft: dict[str, tuple[str, str]]  # key -> (category, status)
    legs: dict[str, str]                  # key -> canonical leg
    services: dict[str, str]              # key -> canonical service


def _key(s: str | None) -> str:
    return (s or "").strip().lower()


def load_mappings() -> Mappings:
    folder = config.DATA_DIR / "mappings"

    def rows(name):
        with (folder / name).open(newline="", encoding="utf-8-sig") as f:
            return list(csv.DictReader(f))

    return Mappings(
        aircraft={_key(r["code"]): (r["category"], r["status"]) for r in rows("aircraft.csv")},
        legs={_key(r["as_logged"]): r["canonical"] for r in rows("legs.csv")},
        services={_key(r["as_logged"]): r["canonical"] for r in rows("services.csv")},
    )


def aircraft_category(m: Mappings, raw: str | None) -> tuple[str, str] | None:
    """(category, status) or None if blank/unknown."""
    return m.aircraft.get(_key(raw))


def leg_of(m: Mappings, raw: str | None) -> str:
    """Canonical leg, or 'missing' (blank) or 'ambiguous' (e.g. 'T')."""
    k = _key(raw)
    if not k:
        return "missing"
    return m.legs.get(k, "ambiguous")


def service_of(m: Mappings, raw: str | None) -> str | None:
    return m.services.get(_key(raw))


# ---------- dates ----------

def parse_date(raw: str | None, period_start: date, period_end: date) -> tuple[date | None, bool]:
    """Return (date or None, year_was_missing). Accepts DD/MM/YYYY, DD/MM/YY, YYYY-MM-DD, DD-Mon.

    A date with no year is only resolved if exactly one candidate year puts it
    inside the batch week; otherwise None.
    """
    s = (raw or "").strip()
    try:
        m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
        if m:
            return date(int(m[3]), int(m[2]), int(m[1])), False
        m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{2})", s)
        if m:
            return date(2000 + int(m[3]), int(m[2]), int(m[1])), False
        m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", s)
        if m:
            return date(int(m[1]), int(m[2]), int(m[3])), False
        m = re.fullmatch(r"(\d{1,2})-([A-Za-z]{3})", s)
        if m and m[2].lower() in _MONTHS:
            found = []
            for year in sorted({period_start.year, period_end.year}):
                try:
                    d = date(year, _MONTHS[m[2].lower()], int(m[1]))
                except ValueError:
                    continue
                if period_start <= d <= period_end:
                    found.append(d)
            return (found[0], True) if len(found) == 1 else (None, True)
    except ValueError:
        return None, False
    return None, False


# ---------- times ----------

def parse_time(raw: str | None) -> int | None:
    """Minutes since midnight, or None if blank or not a clearly formed time.

    Accepted: HH:MM (24h, two-digit hour) and H:MM / HH:MM with am or pm.
    NOT accepted (returned as None, never guessed): '10' (not 10:00), '1010',
    '7:10' with no am/pm (could be morning or evening), '24:00', '12:60',
    '13:00pm', '0:30am'.
    """
    s = (raw or "").strip().lower()
    m = re.fullmatch(r"([01]\d|2[0-3]):([0-5]\d)", s)
    if m:
        return int(m[1]) * 60 + int(m[2])
    m = re.fullmatch(r"(\d{1,2}):([0-5]\d)\s*(am|pm)", s)
    if m:
        hour = int(m[1])
        if not 1 <= hour <= 12:
            return None
        if m[3] == "am":
            hour = 0 if hour == 12 else hour
        else:
            hour = 12 if hour == 12 else hour + 12
        return hour * 60 + int(m[2])
    return None


def hhmm(minutes: int | None) -> str | None:
    return None if minutes is None else f"{minutes // 60:02d}:{minutes % 60:02d}"
