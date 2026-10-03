"""Rate lookup and pro-rata maths. Plain code; never imports anthropic.

Rule: a rate applies only on an exact match of (service, aircraft category, leg).
'Any' on the rate card matches any value (the card says so explicitly). There is
no nearest-rate fallback.
"""
import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from reconciler.models import Hold, HoldReason
from reconciler.normalise import Mappings, _key

CENT = Decimal("0.01")


@dataclass(frozen=True)
class RateEntry:
    service: str
    category: str          # Narrowbody | Widebody | Any
    leg: str               # transit | terminating | Any
    flat: Decimal | None   # AUD per job
    per_minutes: int | None = None  # for pro-rata: the card's block size (e.g. 15)
    prorata_amount: Decimal | None = None  # AUD per block (e.g. 75)

    @property
    def is_prorata(self) -> bool:
        return self.prorata_amount is not None

    @property
    def usable(self) -> bool:
        return self.flat is not None or self.is_prorata

    def label(self) -> str:
        if self.is_prorata:
            return f"AUD {self.prorata_amount} per {self.per_minutes} min, pro-rata per minute"
        return f"AUD {self.flat}"


_PRORATA_RE = re.compile(r"^(\d+(?:\.\d+)?) per (\d+) min \(pro-rata\)$")


def parse_rate_cell(cell: str) -> tuple[Decimal | None, int | None, Decimal | None]:
    """Return (flat, per_minutes, prorata_amount). All None if the cell is not understood."""
    s = (cell or "").strip()
    m = _PRORATA_RE.match(s)
    if m:
        return None, int(m[2]), Decimal(m[1])
    if re.fullmatch(r"\d+(?:\.\d+)?", s):
        return Decimal(s), None, None
    return None, None, None


def load_rates(rate_rows: list[dict], maps: Mappings) -> list[RateEntry]:
    entries = []
    for r in rate_rows:
        flat, per, amt = parse_rate_cell(r["Rate (AUD)"])
        leg_raw = r["Transit / Terminator"].strip()
        leg = "Any" if leg_raw.lower() == "any" else maps.legs.get(_key(leg_raw), leg_raw.lower())
        entries.append(RateEntry(
            service=r["Service"].strip(),
            category=r["Aircraft Category"].strip(),
            leg=leg,
            flat=flat,
            per_minutes=per,
            prorata_amount=amt,
        ))
    return entries


@dataclass(frozen=True)
class Lookup:
    rate: RateEntry | None
    hold: HoldReason | None


def find_rate(rates: list[RateEntry], service: str | None, category: str | None,
              leg: str, aircraft_blank: bool) -> Lookup:
    """Exact match on (service, category, leg). Returns a rate or the reason there is none."""
    if not service or not any(r.service == service for r in rates):
        return Lookup(None, HoldReason(Hold.NO_RATE_SERVICE, "Service is not on the rate card: no agreed price."))
    rows = [r for r in rates if r.service == service]
    matches = [r for r in rows if r.category in ("Any", category) and r.leg in ("Any", leg)]
    if len(matches) == 1:
        if not matches[0].usable:
            return Lookup(None, HoldReason(Hold.RATE_UNUSABLE, "The rate card entry could not be read."))
        return Lookup(matches[0], None)
    if len(matches) > 1:
        return Lookup(None, HoldReason(Hold.RATE_UNUSABLE, "More than one rate matches; cannot choose."))
    # No match: say which field blocked it.
    cat_ok = [r for r in rows if r.category in ("Any", category)]
    if leg in ("ambiguous", "missing") and cat_ok:
        if leg == "ambiguous":
            return Lookup(None, HoldReason(Hold.AMBIGUOUS_LEG, "Transit/terminating is ambiguous as logged, and the rate depends on it."))
        return Lookup(None, HoldReason(Hold.MISSING_LEG, "Transit/terminating is missing, and the rate depends on it."))
    leg_ok = [r for r in rows if r.leg in ("Any", leg)]
    if category is None and leg_ok:
        if aircraft_blank:
            return Lookup(None, HoldReason(Hold.MISSING_AIRCRAFT, "Aircraft type is missing, and the rate depends on it."))
        return Lookup(None, HoldReason(Hold.UNKNOWN_AIRCRAFT, "Aircraft code is not recognised, and the rate depends on it."))
    if leg == "originating":
        return Lookup(None, HoldReason(Hold.NO_RATE_LEG, "Originating flights have no agreed price for this service."))
    return Lookup(None, HoldReason(Hold.NO_RATE_LEG, f"No agreed rate for this service with leg type '{leg}'."))


def prorata_amount(rate: RateEntry, minutes: int) -> Decimal:
    """Per-minute pro-rata: (amount / block) x minutes, rounded to the cent."""
    per_minute = rate.prorata_amount / Decimal(rate.per_minutes)
    return (per_minute * minutes).quantize(CENT, rounding=ROUND_HALF_UP)
