import re
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from streamlit.testing.v1 import AppTest

import config
from reconciler import approval
from reconciler.checks import Check, run_checks
from reconciler.exceptions import TEMPLATES, draft_questions, group_by_owner, load_routing
from reconciler.fixtures import load_fixture_extractions
from reconciler.invoice import build_invoice
from reconciler.loader import load_dataset
from reconciler.models import Hold, Tier


def synthetic_invoice():
    ds = load_dataset("synthetic")
    return build_invoice(ds, load_fixture_extractions("synthetic", len(ds.log_rows)))


# ---------------- exceptions queue ----------------

def test_every_hold_reason_has_a_template_and_a_route():
    routing = load_routing()
    for h in Hold:
        assert h in TEMPLATES, f"no question template for {h}"
        assert h in routing, f"no routing entry for {h}"


def test_routing_priorities_are_unique():
    priorities = [p for _, p in load_routing().values()]
    assert len(priorities) == len(set(priorities))


def test_one_question_per_held_line():
    inv = synthetic_invoice()
    qs = draft_questions(inv)
    assert sorted(q.row_id for q in qs) == sorted(l.row_id for l in inv.held)
    assert len(qs) == 7 and all(q.text.strip() for q in qs)


def test_questions_are_grouped_by_owner():
    groups = group_by_owner(draft_questions(synthetic_invoice()))
    by_row = {q.row_id: owner for owner, qs in groups.items() for q in qs}
    assert by_row[6] == "Operations"            # unknown aircraft code
    assert by_row[12] == "Operations"           # "T"
    assert by_row[13] == "Operations"           # note about an aircraft change
    assert by_row[11] == "Operations"           # impossible time range
    assert by_row[15] == "Rates and contracts"  # service not on the rate card
    assert by_row[10] == "Rates and contracts"  # no rate for that leg type
    assert by_row[7] == "Rates and contracts"   # originating flight not priced


def test_operations_questions_lead_over_rate_questions():
    # A line held for both a rate gap and an ambiguous leg goes to operations first.
    inv = synthetic_invoice()
    line = next(l for l in inv.held if l.row_id == 10)
    from reconciler.models import HoldReason
    line.holds.append(HoldReason(Hold.AMBIGUOUS_LEG, "extra"))
    q = next(q for q in draft_questions(inv) if q.row_id == 10)
    assert q.owner == "Operations" and q.also_open == 1


def test_every_template_fills_without_error_on_awkward_rows():
    inv = synthetic_invoice()
    line = inv.held[0]
    line.raw = {k: "" for k in line.raw}      # blank everything
    from reconciler.models import HoldReason
    line.holds = [HoldReason(h, f"detail for {h.value}") for h in Hold]
    assert draft_questions(inv)               # no KeyError / format error for any hold code


def test_a_note_cannot_break_the_template():
    inv = synthetic_invoice()
    line = next(l for l in inv.held if l.row_id == 13)
    line.raw["Notes"] = "{service} {0} {note} }"
    q = next(q for q in draft_questions(inv) if q.row_id == 13)
    assert "{service} {0} {note} }" in q.text


def test_no_held_lines_means_no_questions():
    ds = load_dataset("synthetic")
    inv = build_invoice(ds, load_fixture_extractions("synthetic", len(ds.log_rows)))
    inv.held.clear()
    assert draft_questions(inv) == []


# ---------------- approval gate ----------------

def ok_checks():
    return [Check("a", True, ""), Check("b", True, ""), Check("c", True, "")]


def test_name_is_required():
    inv = synthetic_invoice()
    for bad in ("", "   ", "x"):
        assert approval.block_reason(inv, ok_checks(), bad)
        with pytest.raises(ValueError):
            approval.approve(inv, ok_checks(), bad)


def test_a_failed_check_blocks_approval():
    inv = synthetic_invoice()
    checks = [Check("Lines sum to the draft total", False, "off by 1"), Check("b", True, ""), Check("c", True, "")]
    assert "Lines sum" in approval.block_reason(inv, checks, "Sam Lee")


def test_approval_records_name_and_time():
    inv = synthetic_invoice()
    a = approval.approve(inv, run_checks(inv), "  Sam   Lee ", now=datetime(2026, 10, 4, 1, 2, tzinfo=timezone.utc))
    assert a.status == approval.APPROVED and a.approver == "Sam Lee" and a.at == "2026-10-04 01:02 UTC"


def test_approval_lapses_if_the_invoice_changes():
    inv = synthetic_invoice()
    a = approval.approve(inv, run_checks(inv), "Sam Lee")
    assert approval.current(a, inv).status == approval.APPROVED
    inv.lines[0].amount += Decimal("1.00")
    assert approval.current(a, inv).status == approval.DRAFT
    assert approval.current(None, inv).status == approval.DRAFT


# ---------------- wording: the app only creates drafts ----------------

def test_no_sending_language_in_ui_or_readme():
    banned = re.compile(r"\b(send|sent|sending|email|e-mail|post|posted|posting|submit|submitted)\b", re.I)
    for rel in ("app.py", "invoice_view.py", "reconciler/exceptions.py", "reconciler/approval.py", "README.md"):
        text = (config.ROOT / rel).read_text(encoding="utf-8")
        assert not banned.findall(text), rel


# ---------------- UI flow ----------------

def test_ui_approval_flow(monkeypatch):
    monkeypatch.setenv("DATASET", "synthetic")
    monkeypatch.setattr(config, "load_dotenv", lambda: None)
    at = AppTest.from_file(str(config.ROOT / "app.py")).run(timeout=60)
    assert not at.exception
    assert any("DRAFT" in w.value for w in at.warning)
    approve_btn = next(b for b in at.button if b.label == "Approve draft")
    assert approve_btn.disabled                                  # no name yet
    at.text_input(key="approver_name").input("Sam Lee").run(timeout=60)
    approve_btn = next(b for b in at.button if b.label == "Approve draft")
    assert not approve_btn.disabled
    approve_btn.click().run(timeout=60)
    assert not at.exception
    assert any("APPROVED by Sam Lee" in s.value for s in at.success)
    next(b for b in at.button if b.label == "Withdraw approval").click().run(timeout=60)
    assert any("DRAFT" in w.value for w in at.warning)


def test_ui_exceptions_tab_lists_owners(monkeypatch):
    monkeypatch.setenv("DATASET", "synthetic")
    monkeypatch.setattr(config, "load_dotenv", lambda: None)
    at = AppTest.from_file(str(config.ROOT / "app.py")).run(timeout=60)
    assert any("ASSUMPTION" in w.value for w in at.warning)
    assert any("Open items (7)" in s.value for s in at.subheader)
