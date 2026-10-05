"""The PDF download: it must show the same numbers as the invoice, keep held lines out of every total,
and never let log text act as formatting. Read back with a PDF reader, so the checks use the real file."""
from datetime import date
from decimal import Decimal
from io import BytesIO

import pytest
from pypdf import PdfReader

from reconciler import approval
from reconciler.fixtures import load_fixture_extractions
from reconciler.indicative import NO_RATE, money
from reconciler.invoice import build_invoice
from reconciler.loader import load_dataset
from reconciler.models import Tier
from reconciler.pdf_export import invoice_pdf, week_label
from tests.test_exceptions_approval import demo_app


def build():
    ds = load_dataset("synthetic")
    return ds, build_invoice(ds, load_fixture_extractions("synthetic", len(ds.log_rows)))


def pdf_text(data: bytes) -> str:
    return "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(data)).pages)


@pytest.fixture(scope="module")
def made():
    ds, inv = build()
    return ds, inv, invoice_pdf(inv, ds.period_start, ds.period_end)


def test_it_is_a_real_pdf_with_the_headings_of_the_shared_layout(made):
    ds, inv, data = made
    assert data.startswith(b"%PDF")
    text = pdf_text(data)
    for heading in ("Draft invoice for review", "Aircraft ground handling", "All amounts in AUD", "Draft total",
                    "Day by day", "Held lines (not in the total)", "Approval", "Approved by (name)", "Date",
                    "Billable now: firm", "Billable now: assumed", "Indicative (AUD)", "Waiting on"):
        assert heading in text, heading
    assert "DRAFT. Not final until a named person has approved it." in text
    assert f"Week of {week_label(ds.period_start, ds.period_end)}" in text


def test_the_total_and_tier_figures_match_the_invoice(made):
    _, inv, data = made
    text = pdf_text(data)
    assert money(inv.draft_total) in text
    assert money(inv.tier_totals[Tier.firm]) in text and money(inv.tier_totals[Tier.assumed]) in text
    assert f"{len(inv.held)} further lines are held" in text


def test_every_billed_line_and_its_amount_appears_and_held_lines_are_in_their_own_table(made):
    _, inv, data = made
    text = pdf_text(data)
    day_part, held_part = text.split("Held lines (not in the total)")
    for day in inv.days:
        for l in day.lines:
            assert l.flight in day_part and money(l.amount) in day_part
        assert money(day.subtotal) in day_part
    for l in inv.held:
        assert l.flight in held_part
        assert l.flight not in day_part or any(l.flight == b.flight for d in inv.days for b in d.lines)


def test_held_amounts_are_never_added_to_a_total():
    _, inv = build()
    assert all(l.amount == Decimal("0.00") for l in inv.held)
    assert inv.draft_total == sum((d.subtotal for d in inv.days), Decimal("0.00"))
    assert inv.tier_totals[Tier.held] == Decimal("0.00") and inv.tier_totals[Tier.duplicate] == Decimal("0.00")


def test_duplicates_are_shown_as_excluded():
    _, inv = build()
    text = pdf_text(invoice_pdf(inv, "2026-11-02", "2026-11-08"))
    assert "Excluded" in text and "Duplicate of row 2. Excluded." in text


def test_an_approved_draft_shows_the_approver_not_the_draft_warning():
    ds, inv = build()
    appr = approval.approve(inv, [], "Sam Lee")
    text = pdf_text(invoice_pdf(inv, ds.period_start, ds.period_end, appr))
    assert "APPROVED by Sam Lee" in text and "DRAFT. Not final" not in text
    assert text.count("Sam Lee") >= 2                      # in the banner and on the approval line


def test_log_text_is_drawn_as_plain_text_never_as_formatting():
    ds, inv = build()
    nasty = '<b>BOLD</b> & <font size="40">HUGE</font> <img src="x"/>'
    first = inv.days[0].lines[0]
    first.flight, first.notes = nasty, [nasty]
    text = pdf_text(invoice_pdf(inv, ds.period_start, ds.period_end))
    assert "<b>BOLD</b>" in text and "<font" in text and "&" in text


def test_text_the_built_in_font_cannot_show_does_not_stop_the_download():
    ds, inv = build()
    inv.days[0].lines[0].service = "Push-back 日本語 ’ ✓"
    data = invoice_pdf(inv, ds.period_start, ds.period_end)
    assert data.startswith(b"%PDF") and "Push-back" in pdf_text(data)


def test_a_clean_invoice_has_no_held_section_and_an_empty_invoice_still_builds():
    ds, inv = build()
    inv.held.clear()
    text = pdf_text(invoice_pdf(inv, ds.period_start, ds.period_end))
    assert "Held lines (not in the total)" not in text and "further line" not in text
    assert invoice_pdf(inv, None, None).startswith(b"%PDF")        # no period given


def test_long_invoices_flow_onto_more_pages_with_a_footer_on_each():
    ds, inv = build()
    base = list(inv.days[0].lines)
    for _ in range(40):
        inv.days[0].lines.extend(base)
    reader = PdfReader(BytesIO(invoice_pdf(inv, ds.period_start, ds.period_end)))
    assert len(reader.pages) >= 3
    for n, page in enumerate(reader.pages, start=1):
        assert f"Page {n}" in page.extract_text()


# ---- the rough cost shown for held lines ----

def test_money_format():
    assert money(Decimal("1410")) == "1,410" and money(Decimal("152.50")) == "152.50" and money(Decimal("0")) == "0"


def test_week_label():
    assert week_label("2026-09-12", "2026-09-18") == "12 to 18 Sep 2026"
    assert week_label(date(2026, 9, 28), date(2026, 10, 4)) == "28 Sep to 4 Oct 2026"
    assert week_label("2026-12-28", "2027-01-03") == "28 Dec 2026 to 3 Jan 2027"
    assert week_label(None, None) == ""


def test_indicative_text_for_the_held_demo_rows():
    _, inv = build()
    got = {l.row_id: l.indicative for l in inv.held}
    assert got[6] == "130 (190 if widebody)"        # aircraft not recognised: narrowbody or widebody price
    assert got[7] == NO_RATE and got[10] == NO_RATE and got[15] == NO_RATE
    assert got[12] == NO_RATE                         # "T": one of the possible legs has no price
    assert all(l.indicative == "" for l in inv.lines if l.tier != Tier.held)


def test_the_indicative_amount_is_display_only():
    ds, inv = build()
    before = (inv.draft_total, dict(inv.tier_totals))
    for l in inv.held:
        l.indicative = "999999"
    invoice_pdf(inv, ds.period_start, ds.period_end)
    assert (inv.draft_total, dict(inv.tier_totals)) == before
    assert "999999" not in str(approval.fingerprint(inv))


# ---- on the page ----

def test_the_page_offers_the_pdf_and_the_csv(monkeypatch):
    at = demo_app(monkeypatch)
    assert not at.exception
    labels = [b.proto.label for b in at.get("download_button")]
    assert "Download draft as PDF" in labels and "Download draft as CSV" in labels
