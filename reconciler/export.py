"""Flat CSV of every line in the draft invoice, for download. Plain code."""
import csv
import io

from reconciler.invoice import Invoice


def _safe(text: str) -> str:
    """Stop spreadsheet apps treating log text as a formula (CSV injection)."""
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def invoice_csv(inv: Invoice) -> str:
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(["row", "date", "flight", "service", "aircraft", "leg", "tier", "rate_applied",
                "amount_aud", "notes", "held_reasons"])
    for l in inv.lines:
        w.writerow([
            l.row_id, l.line_date.isoformat() if l.line_date else "", _safe(l.flight), _safe(l.service),
            _safe(l.aircraft), l.leg, l.tier.value, l.rate_applied, f"{l.amount:.2f}",
            _safe(" ".join(filter(None, [l.assumption] + l.notes))),
            _safe(" | ".join(h.text for h in l.holds)),
        ])
    w.writerow([])
    w.writerow(["DRAFT TOTAL (firm + assumed)", "", "", "", "", "", "", "", f"{inv.draft_total:.2f}"])
    return out.getvalue()
