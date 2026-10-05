"""Assemble priced lines into a day-by-day draft invoice. Plain code; totals are derived here."""
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from reconciler.duplicates import find_duplicates
from reconciler.indicative import indicative_text
from reconciler.loader import Dataset
from reconciler.models import PricedLine, RowExtraction, Tier
from reconciler.normalise import load_mappings
from reconciler.pricing import load_rates
from reconciler.tiering import Context, price_row

ZERO = Decimal("0.00")
BILLED_TIERS = (Tier.firm, Tier.assumed)


@dataclass
class Day:
    day: date | None
    lines: list[PricedLine]
    subtotal: Decimal


@dataclass
class Invoice:
    dataset_name: str
    raw_row_count: int
    lines: list[PricedLine]              # every raw row, one line each, in log order
    days: list[Day]                      # billed lines (firm + assumed) grouped by day
    draft_total: Decimal                 # firm + assumed
    tier_totals: dict[Tier, Decimal]
    tier_counts: dict[Tier, int]
    held: list[PricedLine] = field(default_factory=list)
    duplicates: list[PricedLine] = field(default_factory=list)


# extractions: row_id -> (RowExtraction | None, error text if None)
Extractions = dict[int, tuple[RowExtraction | None, str]]


def build_invoice(ds: Dataset, extractions: Extractions) -> Invoice:
    maps = load_mappings()
    ctx = Context(
        maps=maps,
        rates=load_rates(ds.rate_rows, maps),
        period_start=date.fromisoformat(ds.period_start),
        period_end=date.fromisoformat(ds.period_end),
    )
    dups = find_duplicates(ds.log_rows, maps, ctx.period_start, ctx.period_end)

    lines = []
    for raw in ds.log_rows:
        ext, err = extractions.get(raw["row_id"], (None, "No answer from Claude for this row."))
        lines.append(price_row(raw, ext, ctx, duplicate_of=dups.get(raw["row_id"]), extraction_error=err))

    for l in lines:
        if l.tier == Tier.held:
            l.indicative = indicative_text(l, ctx)      # display only: never part of any total

    billed = [l for l in lines if l.tier in BILLED_TIERS]
    by_day: dict[date | None, list[PricedLine]] = {}
    for l in billed:
        by_day.setdefault(l.line_date, []).append(l)
    days = [Day(d, ls, sum((l.amount for l in ls), ZERO))
            for d, ls in sorted(by_day.items(), key=lambda kv: (kv[0] is None, kv[0]))]

    tier_totals = {t: sum((l.amount for l in lines if l.tier == t), ZERO) for t in Tier}
    tier_counts = {t: sum(1 for l in lines if l.tier == t) for t in Tier}
    return Invoice(
        dataset_name=ds.name,
        raw_row_count=len(ds.log_rows),
        lines=lines,
        days=days,
        draft_total=sum((d.subtotal for d in days), ZERO),
        tier_totals=tier_totals,
        tier_counts=tier_counts,
        held=[l for l in lines if l.tier == Tier.held],
        duplicates=[l for l in lines if l.tier == Tier.duplicate],
    )
