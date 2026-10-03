"""Walk the synthetic set (see data/synthetic/CASES.md) through the whole pipeline."""
from decimal import Decimal

import pytest

from reconciler.checks import run_checks
from reconciler.fixtures import load_fixture_extractions
from reconciler.invoice import build_invoice
from reconciler.loader import load_dataset
from reconciler.models import Hold, Tier

# Independent expectation, written by hand from CASES.md (the app derives its own numbers)
EXPECTED = {
    1: (Tier.firm, "150"), 2: (Tier.firm, "310"), 3: (Tier.duplicate, "0"),
    4: (Tier.assumed, "130"), 5: (Tier.firm, "150"), 6: (Tier.held, "0"),
    7: (Tier.held, "0"), 8: (Tier.firm, "200"), 9: (Tier.firm, "152.00"),
    10: (Tier.held, "0"), 11: (Tier.held, "0"), 12: (Tier.held, "0"),
    13: (Tier.held, "0"), 14: (Tier.firm, "240"), 15: (Tier.held, "0"),
}


@pytest.fixture(scope="module")
def inv():
    ds = load_dataset("synthetic")
    return build_invoice(ds, load_fixture_extractions("synthetic", len(ds.log_rows)))


def test_each_row(inv):
    got = {l.row_id: (l.tier, l.amount) for l in inv.lines}
    for rid, (tier, amt) in EXPECTED.items():
        assert got[rid] == (tier, Decimal(amt)), rid


def test_totals_and_counts(inv):
    assert inv.draft_total == Decimal("1332.00")
    assert inv.tier_counts[Tier.duplicate] == 1
    assert inv.tier_counts[Tier.held] == 7
    assert inv.tier_counts[Tier.assumed] == 1
    assert inv.tier_counts[Tier.firm] == 6
    assert inv.raw_row_count == 15


def test_checks_pass(inv):
    assert all(c.passed for c in run_checks(inv))


def test_hold_reasons(inv):
    by_row = {l.row_id: {h.code for h in l.holds} for l in inv.held}
    assert by_row[6] == {Hold.UNKNOWN_AIRCRAFT, Hold.EXTRACTOR_FLAG} or Hold.UNKNOWN_AIRCRAFT in by_row[6]
    assert Hold.NO_RATE_LEG in by_row[7]            # originating
    assert Hold.NO_RATE_LEG in by_row[10]           # water/waste logged as terminating
    assert Hold.IMPOSSIBLE_TIME in by_row[11]
    assert Hold.AMBIGUOUS_LEG in by_row[12]
    assert Hold.NOTE_NEEDS_ATTENTION in by_row[13]
    assert Hold.NO_RATE_SERVICE in by_row[15]


def test_assumed_line_states_its_assumption(inv):
    line = next(l for l in inv.lines if l.row_id == 4)
    assert line.tier == Tier.assumed and "2026" in line.assumption


def test_same_flight_other_day_is_not_a_duplicate(inv):
    assert [l.tier for l in inv.lines if l.flight == "XA201"] == [Tier.firm, Tier.firm]


def test_gaps_that_do_not_change_price_are_noted_not_held(inv):
    line = next(l for l in inv.lines if l.row_id == 5)
    assert line.tier == Tier.firm and any("End time is missing" in n for n in line.notes)


def test_day_subtotals_sum_to_total(inv):
    assert sum(d.subtotal for d in inv.days) == inv.draft_total
