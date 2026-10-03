"""Rendering of a draft invoice, shared by the demo and upload paths."""
import pandas as pd
import streamlit as st

from reconciler import approval
from reconciler.exceptions import draft_questions, group_by_owner
from reconciler.export import invoice_csv
from reconciler.invoice import Invoice
from reconciler.models import Tier


def aud(x) -> str:
    return f"AUD {x:,.2f}"


def render_status(inv: Invoice) -> None:
    appr = approval.current(st.session_state.get("approval"), inv)
    if appr.status == approval.APPROVED:
        st.success(f"Status: APPROVED by {appr.approver} on {appr.at}.", icon=":material/verified:")
    else:
        st.warning("Status: DRAFT. Not approved.", icon=":material/edit_note:")


def render_exceptions(inv: Invoice) -> None:
    questions = draft_questions(inv)
    st.subheader(f"Open items ({len(questions)})")
    if not questions:
        st.success("No held lines. Nothing needs confirming.")
        return
    st.caption("One drafted question per held line. These are drafts for a person to review; "
               "the lines stay held, and bill 0, until someone confirms them.")
    st.warning("ASSUMPTION: the owner groups below come from a routing table in the repo "
               "(data/mappings/routing.csv). Confirm who really answers each kind of question.")
    for owner, qs in group_by_owner(questions).items():
        st.markdown(f"**{owner}** ({len(qs)})")
        st.dataframe(pd.DataFrame([{
            "Row": q.row_id, "Line": q.context, "Question": q.text,
            "Other open points": q.also_open or "",
        } for q in qs]).set_index("Row"), alt=f"Drafted questions for {owner}")
    st.caption("What happens if nobody answers is not handled in this version: the open items stay listed.")


def render_approval(inv: Invoice, checks) -> None:
    appr = approval.current(st.session_state.get("approval"), inv)
    st.subheader("Approval")
    st.write("Approving records a status in this app. It does not do anything else.")
    n_held = len(inv.held)
    if appr.status == approval.APPROVED:
        st.success(f"APPROVED by {appr.approver} on {appr.at}: draft total {aud(inv.draft_total)}.")
        if n_held:
            st.warning(f"{n_held} held line(s) were not included and remain open.")
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
