"""The three code-verified checks shown in the UI. Each uses a different route to the number."""
from dataclasses import dataclass
from decimal import Decimal

from reconciler.invoice import Invoice
from reconciler.models import Tier


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str


def run_checks(inv: Invoice) -> list[Check]:
    # 1. every line's amount adds up to the draft total (total came from day subtotals)
    lines_sum = sum((l.amount for l in inv.lines), Decimal("0.00"))
    c1 = Check("Lines sum to the draft total", lines_sum == inv.draft_total,
               f"lines {lines_sum} vs total {inv.draft_total}")

    # 2. tier subtotals add up to the draft total, and unbilled tiers are zero
    tiers_sum = sum(inv.tier_totals.values(), Decimal("0.00"))
    unbilled = inv.tier_totals.get(Tier.held, Decimal("0.00")) + inv.tier_totals.get(Tier.duplicate, Decimal("0.00"))
    c2 = Check("Tier subtotals sum to the draft total",
               tiers_sum == inv.draft_total and unbilled == Decimal("0.00"),
               f"tiers {tiers_sum} vs total {inv.draft_total}; held+duplicate billed {unbilled}")

    # 3. raw rows = unique lines + duplicates, and no row appears twice
    unique = sum(1 for l in inv.lines if l.tier != Tier.duplicate)
    dups = sum(1 for l in inv.lines if l.tier == Tier.duplicate)
    ids = [l.row_id for l in inv.lines]
    c3 = Check("Raw rows = unique lines + duplicates",
               inv.raw_row_count == unique + dups and len(set(ids)) == len(ids),
               f"raw {inv.raw_row_count} vs unique {unique} + duplicates {dups}")
    return [c1, c2, c3]
