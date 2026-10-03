"""Streamlit entry point. Thin: loads data, runs the pipeline, renders."""
import hashlib
import os
from datetime import date

import pandas as pd
import streamlit as st

import config
from invoice_view import render_approval, render_exceptions, render_invoice, render_status
from reconciler.access import live_access, session_budget_left
from reconciler.checks import run_checks
from reconciler.invoice import build_invoice
from reconciler.loader import Dataset, DatasetMissing, load_dataset
from reconciler.source import resolve_extractions
from reconciler.upload import UploadError, parse_log, parse_rate_card, suggest_period

config.load_dotenv()
# On a hosted deployment, secrets come from the app settings, not the repo.
for _name in ("ANTHROPIC_API_KEY", "APP_PASSCODE", "ALLOW_OPEN_LIVE"):
    try:
        if _name in st.secrets:
            os.environ.setdefault(_name, str(st.secrets[_name]))
    except Exception:
        pass  # no secrets configured

st.set_page_config(page_title="Invoice reconciler", layout="wide")
st.title("Draft invoice for review")
st.caption("This is a draft. Nothing here has been approved.")

st.session_state.setdefault("live_rows_used", 0)

source_choice = st.sidebar.segmented_control("Source", ["Demo dataset", "Upload a file"],
                                             default="Demo dataset", key="source_choice")

if source_choice != "Upload a file":
    # ---------------- demo dataset (cached Claude results) ----------------
    try:
        ds = load_dataset()
    except DatasetMissing as e:
        st.error(f"{e}. Set DATASET=synthetic to use the bundled demo data.")
        st.stop()

    (st.warning if ds.name == "synthetic" else st.info)(ds.label)
    extractions, source = resolve_extractions(ds)
    (st.info if source.kind == "cached" else st.error)(
        source.banner, icon=":material/cached:" if source.kind == "cached" else None)

    # Local only: re-recording spends credits and overwrites the cache, so never on a hosted app.
    if os.environ.get("ANTHROPIC_API_KEY") and os.environ.get("ALLOW_OPEN_LIVE") == "1":
        with st.sidebar:
            st.subheader("Local only")
            st.caption(f"Model: {config.MODEL}. One API call per row; overwrites this dataset's cache.")
            if st.button("Re-record with Claude", icon=":material/refresh:"):
                from reconciler.cache import save_cache
                from reconciler.extractor import run_live
                with st.spinner("Calling Claude..."):
                    results = run_live(ds.log_rows, ds.period_start, ds.period_end)
                    save_cache(ds.name, ds.log_rows, ds.period_start, ds.period_end, results, config.MODEL)
                st.rerun()

    inv = build_invoice(ds, extractions)
    checks = run_checks(inv)
    render_status(inv)
    tab_inv, tab_exc, tab_appr, tab_raw = st.tabs(["Invoice", "Exceptions", "Approval", "Raw data"])
    with tab_inv:
        render_invoice(inv, checks, f"draft_invoice_{ds.name}.csv")
    with tab_exc:
        render_exceptions(inv)
    with tab_appr:
        render_approval(inv, checks)
    with tab_raw:
        c1, c2 = st.columns(2)
        c1.metric("Job log rows", len(ds.log_rows))
        c2.metric("Rate card rows", len(ds.rate_rows))
        st.markdown("**Job log (raw, as exported)**")
        st.dataframe(pd.DataFrame(ds.log_rows).set_index("row_id"), alt="Raw job log rows")
        st.markdown("**Rate card (raw, as exported)**")
        st.dataframe(pd.DataFrame(ds.rate_rows), alt="Raw rate card rows")

else:
    # ---------------- upload a file (live Claude reading) ----------------
    st.warning("UPLOAD MODE. Rows you upload go to the Anthropic API so Claude can read them. "
               "This app does not store them. Only upload data you are allowed to share this way.", icon=":material/upload:")

    demo_dir = config.dataset_dir("synthetic")
    with st.expander("Expected file format and templates"):
        st.write("Job log columns: " + ", ".join(["Date", "Flight", "Aircraft", "Transit/Term", "Service",
                                                  "Start", "End", "Notes"]) +
                 f". Date and Service are required. Up to {config.MAX_UPLOAD_ROWS} rows.")
        st.write("Rate card columns: Service, Aircraft Category, Transit / Terminator, Rate (AUD).")
        d1, d2 = st.columns(2)
        d1.download_button("Job log template (synthetic)", (demo_dir / "job_log.csv").read_bytes(),
                           file_name="job_log_template.csv", mime="text/csv", icon=":material/download:")
        d2.download_button("Rate card template (synthetic)", (demo_dir / "rate_card.csv").read_bytes(),
                           file_name="rate_card_template.csv", mime="text/csv", icon=":material/download:")

    log_file = st.file_uploader("Job log (.csv or .xlsx)", type=["csv", "xlsx"], max_upload_size=2, key="log_file")
    rate_file = st.file_uploader("Rate card (.csv or .xlsx), optional", type=["csv", "xlsx"], max_upload_size=2,
                                 key="rate_file")
    if log_file is None:
        st.info("Upload a job log to begin.")
        st.stop()

    try:
        log = parse_log(log_file.name, log_file.getvalue())
        if rate_file is not None:
            rates = parse_rate_card(rate_file.name, rate_file.getvalue())
            rate_rows, rate_note = rates.rows, None
        else:
            rate_rows = load_dataset("synthetic").rate_rows
            rate_note = "No rate card uploaded: using the DEMO rate card (synthetic prices). These are not your prices."
    except UploadError as e:
        st.error(str(e))
        st.stop()

    for n in log.notices:
        st.caption(n)
    if rate_note:
        st.warning(rate_note)

    suggested = suggest_period(log.rows)
    period = st.date_input("Batch week (used to read dates that have no year)",
                           value=suggested if suggested else (date.today(), date.today()),
                           key="period")
    if not (isinstance(period, tuple) and len(period) == 2):
        st.info("Pick both a start and an end date.")
        st.stop()
    p_start, p_end = period

    model = st.selectbox("Model", config.UPLOAD_MODELS,
                         index=config.UPLOAD_MODELS.index(config.MODEL) if config.MODEL in config.UPLOAD_MODELS else 0,
                         help="Haiku is cheapest. Sonnet is more careful with notes and unusual entries.")

    passcode = st.text_input("Passcode", type="password") if live_access("").needs_passcode else ""
    access = live_access(passcode)
    if not access.allowed:
        st.info(access.reason)
        st.stop()

    n_rows = len(log.rows)
    left = config.MAX_LIVE_ROWS_PER_SESSION - st.session_state.live_rows_used
    st.caption(f"{n_rows} rows to read. This session has {max(left, 0)} live row reads left.")
    agreed = st.checkbox("I am allowed to share this data with the Anthropic API.")

    run_key = hashlib.sha256(repr((log_file.getvalue(), p_start, p_end, model)).encode()).hexdigest()
    if st.button("Read with Claude and build the draft", type="primary", disabled=not agreed):
        if not session_budget_left(st.session_state.live_rows_used, n_rows, config.MAX_LIVE_ROWS_PER_SESSION):
            st.error("This session's live-read limit would be exceeded. Reload the page to start a new session.")
            st.stop()
        from reconciler.extractor import run_live
        bar = st.progress(0.0, text="Reading rows with Claude...")
        st.session_state.live_rows_used += n_rows
        results = run_live(log.rows, p_start.isoformat(), p_end.isoformat(), model=model,
                           on_progress=lambda d, t: bar.progress(d / t, text=f"Read {d} of {t} rows"))
        bar.empty()
        st.session_state.upload_run = {"key": run_key, "extractions": results, "model": model}

    run = st.session_state.get("upload_run")
    if not run or run["key"] != run_key:
        st.info("Press the button to read this file. Changing the file, week or model needs a new read.")
        st.stop()

    ds = Dataset(name="upload", label="UPLOADED DATA: not verified. Draft only.",
                 period_start=p_start.isoformat(), period_end=p_end.isoformat(),
                 log_rows=log.rows, rate_rows=rate_rows)
    st.info(f"LIVE RESULTS. Read just now by {run['model']}. Not cached or stored by this app. "
            "Rows went to the Anthropic API.", icon=":material/bolt:")
    inv = build_invoice(ds, run["extractions"])
    checks = run_checks(inv)
    render_status(inv)
    tab_inv, tab_exc, tab_appr, tab_raw = st.tabs(["Invoice", "Exceptions", "Approval", "Raw data"])
    with tab_inv:
        render_invoice(inv, checks, "draft_invoice_upload.csv")
    with tab_exc:
        render_exceptions(inv)
    with tab_appr:
        render_approval(inv, checks)
    with tab_raw:
        st.markdown("**Job log (raw, as uploaded)**")
        st.dataframe(pd.DataFrame(log.rows).set_index("row_id"), alt="Uploaded job log rows")
        st.markdown("**Rate card in use**")
        st.dataframe(pd.DataFrame(rate_rows), alt="Rate card in use")
