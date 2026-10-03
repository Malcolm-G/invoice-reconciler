"""Rendering of a draft invoice, shared by the demo and upload paths. Wording is for non-technical readers."""
import re

import pandas as pd
import streamlit as st

from reconciler import approval
from reconciler.exceptions import draft_questions, group_by_owner
from reconciler.export import invoice_csv
from reconciler.invoice import Invoice
from reconciler.models import Tier


def aud(x) -> str:
    return f"AUD {x:,.2f}"


_MD_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+\-.!|<>~$&:])")


def md_escape(value) -> str:
    """st.table renders cell text as Markdown. Log text is untrusted, so show it literally:
    no links, images, bold or HTML can come from a note or a flight number."""
    return _MD_SPECIAL.sub(r"\\\1", str(value if value is not None else ""))


def render_status(inv: Invoice) -> None:
    appr = approval.current(st.session_state.get("approval"), inv)
    if appr.status == approval.APPROVED:
        st.success(f"Status: APPROVED by {appr.approver} on {appr.at}.", icon=":material/verified:")
    else:
        st.warning("Status: DRAFT. Not approved.", icon=":material/edit_note:")


def render_check_warning(checks) -> None:
    """The checks run on every invoice. Nothing is shown unless one fails."""
    if any(not c.passed for c in checks):
        st.error("Something in this draft doesn't add up, so it can't be approved yet. "
                 "Please don't rely on these figures.", icon=":material/error:")


def render_key() -> None:
    with st.container(border=True):
        st.markdown("**How to read this invoice**")
        st.markdown(
            "- **Firm**: confirmed straight from the log. Included in the total.\n"
            "- **Assumed**: included in the total, based on one low-risk guess that is written on the line "
            "(for example, a missing year).\n"
            "- **Held**: needs a person to confirm. Not billed (AUD 0) until someone does.\n"
            "- **Duplicate**: the same entry appeared twice. Counted once.\n\n"
            "The draft total is firm + assumed."
        )


def render_exceptions(inv: Invoice) -> None:
    questions = draft_questions(inv)
    st.subheader(f"Questions to answer ({len(questions)})")
    if not questions:
        st.success("No held lines. Nothing needs confirming.")
        return
    st.caption("These questions would clear the held lines. A person needs to answer them; "
               "until then those lines are not billed.")
    st.warning("ASSUMPTION: who answers each kind of question is our guess. Please confirm with the business.")
    for owner, qs in group_by_owner(questions).items():
        st.markdown(f"**{owner}** ({len(qs)})")
        show_also = any(q.other_reasons for q in qs)   # nothing to show: keep the table simple
        rows = []
        for q in qs:
            row = {"Row": q.row_id, "Line": md_escape(q.context), "Question": md_escape(q.text)}
            if show_also:
                row["Also needs"] = md_escape(" | ".join(q.other_reasons))
            rows.append(row)
        st.table(pd.DataFrame(rows).set_index("Row"), alt=f"Questions for {owner}")


def render_approval(inv: Invoice, checks) -> None:
    appr = approval.current(st.session_state.get("approval"), inv)
    st.subheader("Approval")
    st.write("Approving only marks this draft as approved on this page. Nothing else happens.")
    n_held = len(inv.held)
    if appr.status == approval.APPROVED:
        st.success(f"APPROVED by {appr.approver} on {appr.at}: draft total {aud(inv.draft_total)}.")
        if n_held:
            st.warning(f"{n_held} held line(s) were not included and are still open.")
        if st.button("Withdraw approval", icon=":material/undo:"):
            st.session_state.pop("approval", None)
            st.rerun()
        return
    st.info(f"Approval covers the draft total of {aud(inv.draft_total)} (firm + assumed)."
            + (f" {n_held} held line(s) are not included and stay open." if n_held else ""))
    name = st.text_input("Approver name", key="approver_name")
    reason = approval.block_reason(inv, checks, name)
    if reason:
        st.caption(reason)
    if st.button("Approve draft", type="primary", disabled=reason is not None, icon=":material/check:"):
        st.session_state.approval = approval.approve(inv, checks, name)
        st.rerun()


def render_results(inv: Invoice, checks, download_name: str, show_original) -> None:
    """The whole results page: status, key, then the four tabs. show_original draws the Original data tab."""
    render_status(inv)
    render_check_warning(checks)
    render_key()
    tab_inv, tab_q, tab_appr, tab_orig = st.tabs(["Invoice", "Questions", "Approval", "Original data"])
    with tab_inv:
        render_invoice(inv, download_name)
    with tab_q:
        render_exceptions(inv)
    with tab_appr:
        render_approval(inv, checks)
    with tab_orig:
        show_original()


def render_invoice(inv: Invoice, download_name: str = "draft_invoice.csv") -> None:
    billed = inv.tier_counts[Tier.firm] + inv.tier_counts[Tier.assumed]
    c1, c2, c3, c4 = st.columns([2, 1, 1, 1])   # the total needs the most room
    c1.metric("Draft total", aud(inv.draft_total))
    c2.metric("Lines billed", billed)
    c3.metric("Held lines", len(inv.held))
    c4.metric("Duplicates left out", len(inv.duplicates))

    for day in inv.days:
        st.subheader(day.day.isoformat() if day.day else "Date unresolved")
        rows = [{
            "Row": l.row_id, "Flight": md_escape(l.flight), "Service": md_escape(l.service),
            "Price used": md_escape(l.rate_applied), "Amount": md_escape(aud(l.amount)),
            "Line status": l.tier.value,
            "Note": md_escape(" ".join(filter(None, [l.assumption] + l.notes))),
        } for l in day.lines]
        st.table(pd.DataFrame(rows).set_index("Row"), alt=f"Invoice lines for {day.day}")
        st.markdown(f"**Day subtotal: {aud(day.subtotal)}**")

    st.divider()
    st.subheader("Summary by line status")
    st.table(pd.DataFrame([
        {"Line status": t.value, "Lines": inv.tier_counts[t], "Amount": md_escape(aud(inv.tier_totals[t]))}
        for t in Tier
    ]).set_index("Line status"), alt="Lines and amounts by line status")

    st.subheader(f"Held lines ({len(inv.held)}): not billed until a person confirms them")
    if inv.held:
        st.table(pd.DataFrame([{
            "Row": l.row_id, "Date": md_escape(l.raw.get("Date")), "Flight": md_escape(l.flight),
            "Service": md_escape(l.service), "Why held": md_escape(" | ".join(h.text for h in l.holds)),
        } for l in inv.held]).set_index("Row"), alt="Held lines and the reason each is held")
    else:
        st.write("None.")

    if inv.duplicates:
        st.subheader(f"Duplicate entries left out ({len(inv.duplicates)})")
        st.table(pd.DataFrame([{
            "Row": l.row_id, "Flight": md_escape(l.flight), "Service": md_escape(l.service),
            "Note": md_escape(" ".join(l.notes)),
        } for l in inv.duplicates]).set_index("Row"), alt="Duplicate entries left out of the invoice")

    st.download_button("Download draft as CSV", invoice_csv(inv), file_name=download_name,
                       mime="text/csv", icon=":material/download:")
