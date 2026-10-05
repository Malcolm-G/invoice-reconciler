"""The draft invoice as a PDF, for download. Plain code: it only draws what the Invoice already holds.

Nothing here reads a price from anywhere else, and no text from the log is treated as formatting.
Held lines have their own table and are never part of a total.
"""
from datetime import date
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from reconciler import approval as approval_module
from reconciler.exceptions import draft_questions
from reconciler.indicative import money
from reconciler.invoice import Invoice
from reconciler.models import PricedLine, Tier

NAVY = colors.HexColor("#1f3a5f")
GREY_TEXT = colors.HexColor("#667085")
BAND = colors.HexColor("#f2f4f7")
RULE = colors.HexColor("#d0d5dd")
DRAFT_BG, DRAFT_TEXT = colors.HexColor("#fef3c7"), colors.HexColor("#92400e")
OK_BG, OK_TEXT = colors.HexColor("#dcfae6"), colors.HexColor("#067647")

MARGIN = 45.4
WIDTH = A4[0] - 2 * MARGIN                      # 504.5 pt
LEG_LABEL = {"transit": "Transit", "terminating": "Terminator", "originating": "Originating"}


def _style(name, font="Helvetica", size=8.5, leading=None, color=colors.black, **kw) -> ParagraphStyle:
    return ParagraphStyle(name, fontName=font, fontSize=size, leading=leading or size * 1.3, textColor=color, **kw)


TITLE = _style("title", "Helvetica-Bold", 22, 26, NAVY)
SUBTITLE = _style("subtitle", size=9.5, color=GREY_TEXT)
H2 = _style("h2", "Helvetica-Bold", 13, 16, NAVY, spaceBefore=14, spaceAfter=6)
DAY = _style("day", "Helvetica-Bold", 9.5, 12, NAVY, spaceBefore=8, spaceAfter=4)
HEAD = _style("head", "Helvetica-Bold", 8, 10, NAVY)
HEAD_R = _style("head_r", "Helvetica-Bold", 8, 10, NAVY, alignment=TA_RIGHT)
CELL = _style("cell", size=8.5, leading=11)
CELL_R = _style("cell_r", size=8.5, leading=11, alignment=TA_RIGHT)
CELL_B = _style("cell_b", "Helvetica-Bold", 8.5, 11)
CELL_BR = _style("cell_br", "Helvetica-Bold", 8.5, 11, alignment=TA_RIGHT)
NOTE = _style("note", size=8.5, color=GREY_TEXT, spaceBefore=4)
TOTAL = _style("total", "Helvetica-Bold", 11, 14, colors.white)
TOTAL_R = _style("total_r", "Helvetica-Bold", 11, 14, colors.white, alignment=TA_RIGHT)


def _clean(value) -> str:
    """Text for the PDF's built-in font: anything it cannot show becomes '?', and markup characters are escaped,
    so log text can never act as formatting."""
    text = "" if value is None else str(value)
    return escape(text.encode("cp1252", "replace").decode("cp1252"))


def _p(value, style) -> Paragraph:
    return Paragraph(_clean(value), style)


def _amount(x) -> str:
    return money(x)


def _day_label(d: date | None) -> str:
    return f"{d:%a} {d.day} {d:%b}" if d else "Date unresolved"


def _as_date(value) -> date | None:
    if isinstance(value, date):
        return value
    return date.fromisoformat(value) if value else None


def week_label(start, end) -> str:
    a, b = _as_date(start), _as_date(end)
    if a is None or b is None:
        return ""
    if a.year != b.year:
        return f"{a.day} {a:%b} {a.year} to {b.day} {b:%b} {b.year}"
    if a.month != b.month:
        return f"{a.day} {a:%b} to {b.day} {b:%b} {b.year}"
    return f"{a.day} to {b.day} {b:%b} {b.year}"


def _banner(text: str, bg, fg) -> Table:
    t = Table([[Paragraph(_clean(text), _style("banner", "Helvetica-Bold", 9, 11, fg))]], colWidths=[WIDTH], rowHeights=[22])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), bg), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                           ("LEFTPADDING", (0, 0), (-1, -1), 8)]))
    return t


def _base_style(extra=()) -> TableStyle:
    return TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
        ("BACKGROUND", (0, 0), (-1, 0), BAND),
        *extra,
    ])


def _summary(inv: Invoice) -> list:
    firm, assumed = inv.tier_counts[Tier.firm], inv.tier_counts[Tier.assumed]
    billable = firm + assumed
    rows = [
        [_p("Item", HEAD), _p("Lines", HEAD_R), _p("Amount (AUD)", HEAD_R)],
        [_p("Billable now: firm", CELL), _p(firm, CELL_R), _p(_amount(inv.tier_totals[Tier.firm]), CELL_R)],
        [_p("Billable now: assumed", CELL), _p(assumed, CELL_R), _p(_amount(inv.tier_totals[Tier.assumed]), CELL_R)],
        [_p("Billable now", CELL_B), _p(billable, CELL_BR), _p(_amount(inv.draft_total), CELL_BR)],
        [_p("Draft total", TOTAL), _p(billable, TOTAL_R), _p(_amount(inv.draft_total), TOTAL_R)],
    ]
    t = Table(rows, colWidths=[292.8, 70, 141.7], rowHeights=[18, 18.5, 18.5, 18.5, 22])
    t.setStyle(_base_style([
        ("LINEBELOW", (0, 0), (-1, 3), 0.4, RULE),
        ("BACKGROUND", (0, 3), (-1, 3), BAND),
        ("BACKGROUND", (0, 4), (-1, 4), NAVY),
        ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    out = [Paragraph("Draft total", H2), t]
    notes = []
    if inv.held:
        n = len(inv.held)
        notes.append(f"{n} further line{'s are' if n != 1 else ' is'} held pending confirmation and "
                     f"{'are' if n != 1 else 'is'} not in this total. See Held lines.")
    if inv.duplicates:
        n = len(inv.duplicates)
        notes.append(f"{n} duplicate entr{'ies are' if n != 1 else 'y is'} left out.")
    if notes:
        out.append(Paragraph(_clean(" ".join(notes)), NOTE))
    return out


def _service_cell(line: PricedLine) -> Paragraph:
    sub = ""
    if line.tier in (Tier.firm, Tier.assumed) and line.rate_category:
        category = "Any aircraft" if line.rate_category == "Any" else line.rate_category
        leg = LEG_LABEL.get(line.leg, "")
        sub = " · ".join(x for x in (category, leg) if x)
    html = _clean(line.service)
    if sub:
        html += f"<br/><font size='7' color='#667085'>{_clean(sub)}</font>"
    return Paragraph(html, CELL)


def _day_groups(inv: Invoice) -> list[tuple[date | None, list[PricedLine], object]]:
    groups: dict[date | None, list[PricedLine]] = {}
    subtotals = {}
    for day in inv.days:
        groups[day.day] = list(day.lines)
        subtotals[day.day] = day.subtotal
    for dup in inv.duplicates:
        groups.setdefault(dup.line_date, []).append(dup)
        subtotals.setdefault(dup.line_date, 0)
    return [(d, sorted(groups[d], key=lambda l: l.row_id), subtotals[d])
            for d in sorted(groups, key=lambda d: (d is None, d))]


def _days(inv: Invoice) -> list:
    out = [Paragraph("Day by day", H2)]
    for day, lines, subtotal in _day_groups(inv):
        rows = [[_p("Row", HEAD), _p("Flight", HEAD), _p("Service", HEAD), _p("Amount", HEAD_R), _p("Note", HEAD)]]
        for l in lines:
            if l.tier == Tier.duplicate:
                amount, note = "Excluded", f"Duplicate of row {l.duplicate_of}. Excluded."
            else:
                amount, note = _amount(l.amount), " ".join(filter(None, [l.assumption] + l.notes))
            rows.append([_p(l.row_id, CELL), _p(l.flight, CELL), _service_cell(l), _p(amount, CELL_R), _p(note, CELL)])
        rows.append([_p("Billable now", CELL_B), "", "", _p(_amount(subtotal), CELL_BR), ""])
        last = len(rows) - 1
        t = Table(rows, colWidths=[34, 51, 137.5, 50, 232], repeatRows=1)
        t.setStyle(_base_style([
            ("LINEBELOW", (0, 0), (-1, last - 1), 0.4, RULE),
            ("BACKGROUND", (0, last), (-1, last), BAND),
            ("SPAN", (0, last), (2, last)),
        ]))
        out.append(KeepTogether([Paragraph(_day_label(day), DAY), t]))
    return out


def _held(inv: Invoice) -> list:
    if not inv.held:
        return []
    questions = {q.row_id: q for q in draft_questions(inv)}
    rows = [[_p("Row", HEAD), _p("Flight", HEAD), _p("Service", HEAD), _p("Waiting on", HEAD),
             _p("Indicative (AUD)", HEAD_R)]]
    for l in inv.held:
        q = questions.get(l.row_id)
        waiting = f"{q.owner}: {q.text}" if q else "; ".join(h.text for h in l.holds)
        rows.append([_p(l.row_id, CELL), _p(l.flight, CELL), _p(l.service, CELL), _p(waiting, CELL),
                     _p(l.indicative, CELL_R)])
    t = Table(rows, colWidths=[34, 51, 90.5, 209, 120], repeatRows=1)
    t.setStyle(_base_style([("LINEBELOW", (0, 0), (-1, -2), 0.4, RULE)]))
    return [Paragraph("Held lines (not in the total)", H2), t]


def _approval(appr) -> list:
    approved = appr is not None and appr.status == approval_module.APPROVED
    label = _style("label", "Helvetica-Bold", 8.5, 11)
    t = Table([[_p("Approved by (name)", label), _p(appr.approver if approved else "", CELL),
                _p("Date", label), _p(appr.at if approved else "", CELL)]],
              colWidths=[123.6, 199, 46, 112], rowHeights=[26], hAlign="LEFT")
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "BOTTOM"), ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (1, 0), (1, 0), 0.7, colors.black), ("LINEBELOW", (3, 0), (3, 0), 0.7, colors.black),
        ("LEFTPADDING", (0, 0), (0, 0), 16.6), ("RIGHTPADDING", (0, 0), (0, 0), 0),
    ]))
    return [KeepTogether([Paragraph("Approval", H2), Spacer(1, 6), t])]


def invoice_pdf(inv: Invoice, period_start=None, period_end=None, approval=None) -> bytes:
    """The draft invoice as PDF bytes. `approval` is the page's current approval (or None for a plain draft)."""
    week = week_label(period_start, period_end)
    heading = f"Draft invoice for review  |  Week of {week}" if week else "Draft invoice for review"
    approved = approval is not None and approval.status == approval_module.APPROVED

    story = [
        Paragraph("Draft invoice for review", TITLE),
        Paragraph(_clean("  |  ".join(filter(None, ["Aircraft ground handling", f"Week of {week}" if week else "",
                                                     "All amounts in AUD"]))).replace("  ", "&nbsp; "), SUBTITLE),
        Spacer(1, 10),
    ]
    if approved:
        story.append(_banner(f"APPROVED by {approval.approver} on {approval.at}. Draft total AUD "
                             f"{_amount(inv.draft_total)}.", OK_BG, OK_TEXT))
    else:
        story.append(_banner("DRAFT. Not final until a named person has approved it.", DRAFT_BG, DRAFT_TEXT))
    story += _summary(inv) + _days(inv) + _held(inv) + _approval(approval)

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(GREY_TEXT)
        canvas.drawString(MARGIN, 28, _plain(heading))
        canvas.drawRightString(A4[0] - MARGIN, 28, f"Page {doc.page}")
        canvas.restoreState()

    buf = BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=40, bottomMargin=54,
                      title="Draft invoice for review", author="").build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()


def _plain(text: str) -> str:
    return text.encode("cp1252", "replace").decode("cp1252")
