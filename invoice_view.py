"""Rendering of a draft invoice, shared by the demo and upload paths."""
import pandas as pd
import streamlit as st

from reconciler.export import invoice_csv
from reconciler.invoice import Invoice
from reconciler.models import Tier


def aud(x) -> str:
    return f"AUD {x:,.2f}"


def render_invoice(inv: Invoice, checks, download_name: str = "draft_invoice.csv") -> None:
    for day in inv.days:
        st.subheader(day.day.isoformat() if day.day else "Date unresolved")
        rows = [{
            "Row": l.row_id, "Flight": l.flight, "Service": l.service, "Aircraft": l.aircraft,
            "Leg": l.leg, "Rate applied": l.rate_applied, "Tier": l.tier.value,
            "Amount": aud(l.amount),
            "Note": " ".join(filter(None, [l.assumption] + l.notes)),
        } for l in day.lines]
        st.dataframe(pd.DataFrame(rows).set_index("Row"), alt=f"Invoice lines for {day.day}")
        st.markdown(f"**Day subtotal: {aud(day.subtotal)}**")

    st.divider()
    st.header(f"Draft total (firm + assumed): {aud(inv.draft_total)}")

    st.subheader("Tier breakdown")
    st.dataframe(pd.DataFrame([
        {"Tier": t.value, "Lines": inv.tier_counts[t], "Amount": aud(inv.tier_totals[t])} for t in Tier
    ]).set_index("Tier"), alt="Lines and amounts by tier")

    st.subheader(f"Held items ({len(inv.held)}): billed 0 until confirmed")
    if inv.held:
        st.dataframe(pd.DataFrame([{
            "Row": l.row_id, "Date": l.raw.get("Date"), "Flight": l.flight, "Service": l.service,
            "Why held": " | ".join(h.text for h in l.holds),
        } for l in inv.held]).set_index("Row"), alt="Held lines and the reason each is held")
    else:
        st.write("None.")

    if inv.duplicates:
        st.subheader(f"Duplicates excluded ({len(inv.duplicates)})")
        st.dataframe(pd.DataFrame([{
            "Row": l.row_id, "Flight": l.flight, "Service": l.service, "Note": " ".join(l.notes),
        } for l in inv.duplicates]).set_index("Row"), alt="Duplicate lines excluded from the invoice")

    st.subheader("Code-verified checks")
    for c in checks:
        (st.success if c.passed else st.error)(f"{'PASS' if c.passed else 'FAIL'}: {c.name} ({c.detail})")

    st.download_button("Download draft as CSV", invoice_csv(inv), file_name=download_name,
                       mime="text/csv", icon=":material/download:")
