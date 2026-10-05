"""A rough "what it might cost" for a held line, shown on the PDF only. Plain code, display only.

It is never added to any total. It only helps a reader see what the answer to a held line could change.
"""
from decimal import Decimal

from reconciler.models import PricedLine
from reconciler.normalise import aircraft_category, leg_of, parse_time, service_of
from reconciler.pricing import RateEntry, prorata_amount

NO_RATE = "No agreed rate"
KNOWN_LEGS = ("transit", "terminating")


def money(x: Decimal) -> str:
    """Whole amounts without cents (1,410), otherwise two decimals (1,410.50)."""
    return f"{x:,.0f}" if x == x.to_integral_value() else f"{x:,.2f}"


def _distinct_amounts(rows: list[RateEntry], minutes: int | None) -> dict[Decimal, RateEntry]:
    out: dict[Decimal, RateEntry] = {}
    for r in rows:
        if r.flat is not None:
            amount = r.flat
        elif r.is_prorata and minutes:
            amount = prorata_amount(r, minutes)
        else:
            continue
        out.setdefault(amount, r)
    return out


def _what_differs(low: RateEntry, high: RateEntry) -> str:
    if low.category != high.category:
        return high.category.lower()
    if low.leg != high.leg:
        return high.leg
    return "the other price applies"


def indicative_text(line: PricedLine, ctx) -> str:
    raw, maps = line.raw, ctx.maps
    service = service_of(maps, raw.get("Service"))
    if not service:
        return NO_RATE
    rows = [r for r in ctx.rates if r.service == service and r.usable]

    cat = aircraft_category(maps, raw.get("Aircraft"))
    if cat:
        rows = [r for r in rows if r.category in ("Any", cat[0])]

    leg = leg_of(maps, raw.get("Transit/Term"))
    if leg in KNOWN_LEGS or leg == "originating":
        rows = [r for r in rows if r.leg in ("Any", leg)]
    elif not all(any(r.leg in ("Any", k) for r in rows) for k in KNOWN_LEGS):
        return NO_RATE            # the leg is unclear and one of the possible legs has no price

    start, end = parse_time(raw.get("Start")), parse_time(raw.get("End"))
    minutes = end - start if start is not None and end is not None and end > start else None
    amounts = _distinct_amounts(rows, minutes)
    if not amounts:
        return NO_RATE
    ordered = sorted(amounts)
    low, high = ordered[0], ordered[-1]
    if low == high:
        return money(low)
    if len(ordered) == 2:
        return f"{money(low)} ({money(high)} if {_what_differs(amounts[low], amounts[high])})"
    return f"{money(low)} to {money(high)}"
