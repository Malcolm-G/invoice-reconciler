"""Turns one raw row (+ Claude's extraction) into a PricedLine with exactly one tier.

Principles (kept deliberately simple so they can be explained):
  * Code reads every field itself from the raw text. Claude's extraction is a
    cross-check: if it disagrees with code on any field, the line is held.
  * The price comes only from code-read fields. Claude cannot raise or set an amount.
  * Claude can only ADD caution (flags, note reading); it can never remove a hold
    that code found.
  * A note passes only if Claude says it just restates a gap AND code independently
    sees that gap. Any other note holds the line.
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from reconciler.models import (FlagType, Hold, HoldReason, NoteKind, PricedLine,
                               RowExtraction, Tier)
from reconciler.normalise import (Mappings, _key, aircraft_category, hhmm, leg_of,
                                  parse_date, parse_time, service_of)
from reconciler.pricing import RateEntry, find_rate, prorata_amount

# Claude flag types that force a hold. Others are informational: code decides on its own.
HOLDING_FLAGS = {
    FlagType.ambiguous_abbreviation,
    FlagType.impossible_time_range,
    FlagType.note_needs_attention,
    FlagType.other_uncertainty,
}


@dataclass(frozen=True)
class Context:
    maps: Mappings
    rates: list[RateEntry]
    period_start: date
    period_end: date


def _mismatches(ext: RowExtraction, d: date | None, year_missing: bool, raw: dict,
                leg: str, service: str | None, start: int | None, end: int | None,
                maps: Mappings) -> list[str]:
    bad = []
    if ext.date_iso != (d.isoformat() if d else None) or (d is not None and ext.date_year_missing != year_missing):
        bad.append("date")
    if _key(ext.flight) != _key(raw.get("Flight")):
        bad.append("flight")
    if _key(ext.aircraft_as_logged) != _key(raw.get("Aircraft")):
        bad.append("aircraft")
    if ext.leg_type.value != leg:
        bad.append("transit/terminating")
    ext_service = service_of(maps, ext.service_as_logged)
    if ext_service != service or (service is None and _key(ext.service_as_logged) != _key(raw.get("Service"))):
        bad.append("service")
    if ext.start_time != hhmm(start):
        bad.append("start time")
    if ext.end_time != hhmm(end):
        bad.append("end time")
    return bad


def price_row(raw: dict, ext: RowExtraction | None, ctx: Context,
              duplicate_of: int | None = None, extraction_error: str = "") -> PricedLine:
    maps = ctx.maps
    d, year_missing = parse_date(raw.get("Date"), ctx.period_start, ctx.period_end)
    cat = aircraft_category(maps, raw.get("Aircraft"))
    category = cat[0] if cat else None
    aircraft_blank = not _key(raw.get("Aircraft"))
    leg = leg_of(maps, raw.get("Transit/Term"))
    service = service_of(maps, raw.get("Service"))
    start = parse_time(raw.get("Start"))
    end = parse_time(raw.get("End"))

    line = PricedLine(
        row_id=raw["row_id"], raw=raw, tier=Tier.held, line_date=d,
        flight=(raw.get("Flight") or "").strip(),
        aircraft=(raw.get("Aircraft") or "").strip() or "(blank)",
        leg=leg, service=service or (raw.get("Service") or "").strip(),
    )

    if duplicate_of is not None:
        line.tier = Tier.duplicate
        line.duplicate_of = duplicate_of
        line.notes.append(f"Same as row {duplicate_of}, so counted once.")
        return line

    holds: list[HoldReason] = []
    notes: list[str] = []

    # --- Claude's output: validated or the row is held (fail safe) ---
    if ext is None:
        holds.append(HoldReason(Hold.EXTRACTION_INVALID,
                                extraction_error or "No usable answer from Claude for this row."))
    else:
        bad = _mismatches(ext, d, year_missing, raw, leg, service, start, end, maps)
        if bad:
            holds.append(HoldReason(Hold.EXTRACTION_MISMATCH,
                                    "Claude's reading and our own check disagree on: " + ", ".join(bad) + ". A person should confirm."))
        for f in ext.flags:
            if f.type in HOLDING_FLAGS:
                holds.append(HoldReason(Hold.EXTRACTOR_FLAG, f"Claude flagged this: {f.reason}"))

    # --- date ---
    assumption = None
    if d is None:
        holds.append(HoldReason(Hold.DATE_UNRESOLVED, "The date couldn't be placed in the week covered."))
    elif year_missing:
        assumption = (f"No year in the log; assumed {d.year} from the week covered "
                      f"({ctx.period_start.isoformat()} to {ctx.period_end.isoformat()}).")

    # --- time sanity (any service) ---
    if start is not None and end is not None and end < start:
        holds.append(HoldReason(Hold.IMPOSSIBLE_TIME, "End time is before start time."))

    # --- rate lookup (exact match only) ---
    lookup = find_rate(ctx.rates, service, category, leg, aircraft_blank)
    rate = lookup.rate
    amount = Decimal("0.00")
    rate_applied = ""
    if lookup.hold:
        holds.append(lookup.hold)
    elif rate is not None:
        if rate.is_prorata:
            if start is None or end is None:
                holds.append(HoldReason(Hold.DURATION_NEEDED,
                                        "Start or end time is missing or unreadable, and the price depends on duration."))
            elif end <= start:
                if not any(h.code == Hold.IMPOSSIBLE_TIME for h in holds):
                    holds.append(HoldReason(Hold.IMPOSSIBLE_TIME, "Start and end times give no duration, and the price depends on duration."))
            else:
                minutes = end - start
                amount = prorata_amount(rate, minutes)
                per_min = rate.prorata_amount / Decimal(rate.per_minutes)
                rate_applied = f"{minutes} min at AUD {per_min:.2f} per minute"
                notes.append("Pro-rata read as per minute; confirm with ops.")
        else:
            amount = rate.flat
            rate_applied = rate.label()

    # --- one-line notes on judgment calls (only if the line is priced) ---
    if rate is not None and not lookup.hold:
        if not rate.is_prorata:
            for label, value, raw_value in (("Start", start, raw.get("Start")), ("End", end, raw.get("End"))):
                if value is None:
                    shown = (raw_value or "").strip()
                    what = f"{label} time '{shown}' isn't a clear time" if shown else f"{label} time missing"
                    notes.append(f"{what}. Doesn't affect the price.")
        if rate.category == "Any" and (category is None):
            what = "not given" if aircraft_blank else f"'{raw.get('Aircraft')}' not recognised"
            notes.append(f"Aircraft {what}. Doesn't affect the price.")
        if rate.leg == "Any" and leg in ("ambiguous", "missing"):
            notes.append("Flight type unclear. Doesn't affect the price.")
        if rate.category != "Any" and cat and cat[1] == "assumed":
            notes.append(f"Aircraft '{raw.get('Aircraft').strip()}' counted as {cat[0].lower()} (our assumption).")

    # --- the log's own note ---
    log_note = (raw.get("Notes") or "").strip()
    gap_seen = start is None or end is None or category is None
    unpriced_seen = any(h.code in (Hold.NO_RATE_SERVICE, Hold.NO_RATE_LEG) for h in holds)
    if log_note:
        kind = ext.note_kind if ext else None
        ok = (kind == NoteKind.restates_gap and gap_seen) or (kind == NoteKind.restates_unpriced and unpriced_seen)
        if not ok:
            holds.append(HoldReason(Hold.NOTE_NEEDS_ATTENTION, f"Log note needs a person to read it: \"{log_note}\""))
        elif not holds:
            notes.append(f"Log note \"{log_note}\": doesn't affect the price.")
    elif ext is not None and ext.note_kind != NoteKind.none:
        holds.append(HoldReason(Hold.EXTRACTION_MISMATCH, "Claude reported a note that isn't in the log."))

    # --- tier ---
    if holds:
        line.tier = Tier.held
        line.holds = holds
        line.notes = notes
        return line
    line.tier = Tier.assumed if assumption else Tier.firm
    line.assumption = assumption
    line.amount = amount
    line.rate_applied = rate_applied
    line.notes = notes
    return line
