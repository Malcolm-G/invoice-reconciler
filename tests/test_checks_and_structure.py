import copy
import re
from decimal import Decimal

import config

from reconciler.checks import run_checks
from reconciler.fixtures import load_fixture_extractions
from reconciler.invoice import build_invoice
from reconciler.loader import load_dataset
from reconciler.models import RowExtraction, Tier


def fresh():
    ds = load_dataset("synthetic")
    return build_invoice(ds, load_fixture_extractions("synthetic", len(ds.log_rows)))


def test_checks_pass_on_good_invoice():
    assert all(c.passed for c in run_checks(fresh()))


def test_check1_fails_if_a_line_amount_is_tampered():
    inv = fresh()
    inv.lines[0].amount += Decimal("1.00")
    c = run_checks(inv)
    assert not c[0].passed


def test_check2_fails_if_tier_subtotals_disagree():
    inv = fresh()
    inv.tier_totals[Tier.firm] += Decimal("5.00")
    assert not run_checks(inv)[1].passed


def test_check2_fails_if_a_held_line_is_billed():
    inv = fresh()
    inv.tier_totals[Tier.held] = Decimal("10.00")
    assert not run_checks(inv)[1].passed


def test_check3_fails_if_a_row_goes_missing():
    inv = fresh()
    inv.lines.pop()
    assert not run_checks(inv)[2].passed


def test_check3_fails_if_a_row_is_counted_twice():
    inv = fresh()
    inv.lines.append(copy.copy(inv.lines[0]))
    assert not run_checks(inv)[2].passed


# ---- structure: Claude never calculates ----

def test_schema_has_no_money_fields():
    banned = re.compile(r"price|amount|total|rate|cost|aud|fee|charge", re.I)
    assert not [f for f in RowExtraction.model_fields if banned.search(f)]


def test_logic_modules_never_import_anthropic():
    pkg = config.ROOT / "reconciler"
    for name in ("pricing", "tiering", "duplicates", "invoice", "checks", "normalise", "models"):
        text = (pkg / f"{name}.py").read_text(encoding="utf-8")
        assert not re.search(r"^\s*(import|from)\s+anthropic", text, re.M), name
