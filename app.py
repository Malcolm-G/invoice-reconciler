"""Streamlit entry point. Thin: loads data, runs the pipeline, renders."""
import os

import pandas as pd
import streamlit as st

import config
from reconciler.checks import run_checks
from reconciler.invoice import build_invoice
from reconciler.loader import DatasetMissing, load_dataset
from reconciler.models import Tier
from reconciler.source import resolve_extractions

config.load_dotenv()
st.set_page_config(page_title="Invoice reconciler", layout="wide")


def aud(x) -> str:
    return f"AUD {x:,.2f}"


try:
    ds = load_dataset()
except DatasetMissing as e:
    st.error(f"{e}. Set DATASET=synthetic to use the bundled demo data.")
    st.stop()

st.title("Draft invoice for review")
st.caption("This is a draft. Nothing here has been approved.")
(st.warning if ds.name == "synthetic" else st.info)(ds.label)

extractions, source = resolve_extractions(ds)
(st.info if source.kind == "cached" else st.error)(source.banner, icon=":material/cached:" if source.kind == "cached" else None)

# Re-recording needs an API key, so this only appears on a machine that has one.
if os.environ.get("ANTHROPIC_API_KEY"):
    with st.sidebar:
        st.subheader("Local only")
        st.caption(f"Model: {config.MODEL}. Makes one API call per row and overwrites the cache.")
        if st.button("Re-record with Claude", icon=":material/refresh:"):
            from reconciler.cache import save_cache
            from reconciler.extractor import run_live
            with st.spinner("Calling Claude, one row at a time..."):
                results = run_live(ds.log_rows, ds.period_start, ds.period_end)
                save_cache(ds.name, ds.log_rows, ds.period_start, ds.period_end, results, config.MODEL)
            st.rerun()

inv = build_invoice(ds, extractions)
checks = run_checks(inv)

tab_inv, tab_raw = st.tabs(["Invoice", "Raw data"])

with tab_inv:
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

with tab_raw:
    c1, c2 = st.columns(2)
    c1.metric("Job log rows", len(ds.log_rows))
    c2.metric("Rate card rows", len(ds.rate_rows))
    st.markdown("**Job log (raw, as exported)**")
    st.dataframe(pd.DataFrame(ds.log_rows).set_index("row_id"), alt="Raw job log rows")
    st.markdown("**Rate card (raw, as exported)**")
    st.dataframe(pd.DataFrame(ds.rate_rows), alt="Raw rate card rows")
