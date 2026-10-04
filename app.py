"""Streamlit entry point. Thin: loads data, runs the pipeline, renders."""
import hashlib
import os
from datetime import date

import pandas as pd
import streamlit as st

import config
from invoice_view import render_results
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

st.session_state.setdefault("live_rows_used", 0)

choice = st.segmented_control("Choose a view", ["Upload a file", "Demo dataset"],
                              default="Upload a file", key="source_choice")
upload_mode = choice != "Demo dataset"   # upload is the default; deselecting falls back to it

if upload_mode:
    st.info("Enter the passcode below to upload your own job log, "
            "or switch to “Demo dataset” above to see an example first.")
else:
    st.info("This is an example using made-up flights, dates and prices. To try your own file, "
            "switch to “Upload a file” above (you will need the passcode).")

if not upload_mode:
    # ---------------- demo dataset (answers Claude gave earlier) ----------------
    try:
        ds = load_dataset()
    except DatasetMissing as e:
        st.error(f"{e}. Set DATASET=synthetic to use the bundled demo data.")
        st.stop()

    if ds.name != "synthetic":
        st.info(ds.label)   # the example-data note above already covers the synthetic set
    extractions, source = resolve_extractions(ds)
    (st.info if source.kind == "cached" else st.warning)(
        source.banner, icon=":material/history:" if source.kind == "cached" else None)

    # Local only: re-recording spends credits and overwrites the saved answers, so never on a hosted app.
    if os.environ.get("ANTHROPIC_API_KEY") and os.environ.get("ALLOW_OPEN_LIVE") == "1":
        with st.sidebar:
            st.subheader("Local only")
            st.caption(f"Model: {config.MODEL}. One API call per row; replaces this dataset's recorded answers.")
            if st.button("Re-record with Claude", icon=":material/refresh:"):
                from reconciler.cache import save_cache
                from reconciler.extractor import run_live
                with st.spinner("Calling Claude..."):
                    results = run_live(ds.log_rows, ds.period_start, ds.period_end)
                    save_cache(ds.name, ds.log_rows, ds.period_start, ds.period_end, results, config.MODEL)
                st.rerun()

    inv = build_invoice(ds, extractions)

    def show_original():
        st.markdown("**Job log, exactly as provided**")
        st.dataframe(pd.DataFrame(ds.log_rows).set_index("row_id"), alt="Job log rows as provided")
        st.markdown("**Price list, exactly as provided**")
        st.dataframe(pd.DataFrame(ds.rate_rows), alt="Price list rows as provided")

    render_results(inv, run_checks(inv), f"draft_invoice_{ds.name}.csv", show_original)

else:
    # ---------------- upload a file (Claude reads it live) ----------------
    passcode = st.text_input("Passcode", type="password") if live_access("").needs_passcode else ""
    access = live_access(passcode)
    if not access.allowed:
        if passcode or not access.needs_passcode:     # the note at the top already asks for the passcode
            st.info(access.reason + " Or switch to “Demo dataset” above to see an example.")
        st.stop()

    st.warning("Your file is read by Claude, an AI model from Anthropic, so its contents are shared with "
               "Anthropic. This app does not keep your file. Only upload data you are allowed to share "
               "this way.", icon=":material/upload:")

    demo_dir = config.dataset_dir("synthetic")
    with st.expander("Need a template?"):
        st.write(f"Your job log needs at least a Date and a Service column (up to {config.MAX_UPLOAD_ROWS} rows). "
                 "The price list is optional.")
        d1, d2 = st.columns(2)
        d1.download_button("Job log template (example data)", (demo_dir / "job_log.csv").read_bytes(),
                           file_name="job_log_template.csv", mime="text/csv", icon=":material/download:")
        d2.download_button("Price list template (example data)", (demo_dir / "rate_card.csv").read_bytes(),
                           file_name="price_list_template.csv", mime="text/csv", icon=":material/download:")

    log_file = st.file_uploader("Job log (.csv or .xlsx)", type=["csv", "xlsx"], max_upload_size=2, key="log_file")
    rate_file = st.file_uploader("Price list (.csv or .xlsx), optional", type=["csv", "xlsx"], max_upload_size=2,
                                 key="rate_file")
    if log_file is None:
        st.stop()

    try:
        log = parse_log(log_file.name, log_file.getvalue())
        if rate_file is not None:
            rate_rows, rate_note = parse_rate_card(rate_file.name, rate_file.getvalue()).rows, None
        else:
            rate_rows = load_dataset("synthetic").rate_rows
            rate_note = "No price list uploaded: using the example price list. These are not your prices."
    except UploadError as e:
        st.error(str(e))
        st.stop()

    for n in log.notices:
        st.caption(n)
    if rate_note:
        st.warning(rate_note)

    suggested = suggest_period(log.rows)
    period = st.date_input("Week covered (needed to read dates that have no year)",
                           value=suggested if suggested else (date.today(), date.today()), key="period")
    if not (isinstance(period, tuple) and len(period) == 2):
        st.info("Pick both a start and an end date.")
        st.stop()
    p_start, p_end = period

    labels = list(config.UPLOAD_CHOICES)
    default_label = next((l for l in labels if config.UPLOAD_CHOICES[l] == config.MODEL), labels[0])
    version = st.selectbox("Claude version", labels, index=labels.index(default_label),
                           help="Haiku is faster and cheaper. Sonnet is more careful with notes and unusual entries.")
    model_id = config.UPLOAD_CHOICES[version]

    n_rows = len(log.rows)
    left = config.MAX_LIVE_ROWS_PER_SESSION - st.session_state.live_rows_used
    st.caption(f"{n_rows} rows will be read."
               + (f" This session has {max(left, 0)} row reads left." if left < 3 * n_rows else ""))
    agreed = st.checkbox("I'm allowed to share this data with Anthropic's Claude.")

    run_key = hashlib.sha256(repr((log_file.getvalue(), p_start, p_end, model_id)).encode()).hexdigest()
    if st.button("Build the draft invoice", type="primary", disabled=not agreed):
        if not session_budget_left(st.session_state.live_rows_used, n_rows, config.MAX_LIVE_ROWS_PER_SESSION):
            st.error("This session has reached its limit. Reload the page to start a new session.")
            st.stop()
        from reconciler.extractor import run_live
        bar = st.progress(0.0, text="Reading rows with Claude...")
        st.session_state.live_rows_used += n_rows
        results = run_live(log.rows, p_start.isoformat(), p_end.isoformat(), model=model_id,
                           on_progress=lambda d, t: bar.progress(d / t, text=f"Read {d} of {t} rows"))
        bar.empty()
        st.session_state.upload_run = {"key": run_key, "extractions": results, "model": model_id}

    run = st.session_state.get("upload_run")
    if not run or run["key"] != run_key:
        st.info("Press the button to read this file. If you change the file, the week or the Claude version, "
                "press it again.")
        st.stop()

    ds = Dataset(name="upload", label="Your uploaded file. Not verified. Draft only.",
                 period_start=p_start.isoformat(), period_end=p_end.isoformat(),
                 log_rows=log.rows, rate_rows=rate_rows)
    st.info(f"Read just now by {config.MODEL_LABELS.get(run['model'], run['model'])}. "
            "This app did not save your file.", icon=":material/bolt:")
    inv = build_invoice(ds, run["extractions"])

    def show_original():
        st.markdown("**Your job log, as uploaded**")
        st.dataframe(pd.DataFrame(log.rows).set_index("row_id"), alt="Uploaded job log rows")
        st.markdown("**Price list in use**")
        st.dataframe(pd.DataFrame(rate_rows), alt="Price list in use")

    render_results(inv, run_checks(inv), "draft_invoice_upload.csv", show_original)
