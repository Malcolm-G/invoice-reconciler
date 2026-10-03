"""Approval gate. The app only creates drafts; approving records a status in this app session and
does nothing else. Plain code, no I/O.

The approval is tied to a fingerprint of the invoice's lines, so if the data, the reading or the
rates change, the status returns to DRAFT.
"""
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone

from reconciler.checks import Check
from reconciler.invoice import Invoice

DRAFT = "DRAFT"
APPROVED = "APPROVED"


@dataclass(frozen=True)
class Approval:
    status: str
    approver: str = ""
    at: str = ""
    fingerprint: str = ""


def fingerprint(inv: Invoice) -> str:
    parts = [(l.row_id, l.tier.value, str(l.amount)) for l in inv.lines] + [("total", str(inv.draft_total))]
    return hashlib.sha256(repr(parts).encode()).hexdigest()[:20]


def clean_name(name: str) -> str:
    return " ".join((name or "").split())


def block_reason(inv: Invoice, checks: list[Check], approver: str) -> str | None:
    """None if approval is allowed, otherwise the reason it is not."""
    if len(clean_name(approver)) < 2:
        return "Enter the approver's name."
    failed = [c.name for c in checks if not c.passed]
    if failed:
        return "A check failed: " + "; ".join(failed) + "."
    return None


def approve(inv: Invoice, checks: list[Check], approver: str, now: datetime | None = None) -> Approval:
    reason = block_reason(inv, checks, approver)
    if reason:
        raise ValueError(reason)
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M UTC")
    return Approval(APPROVED, clean_name(approver), stamp, fingerprint(inv))


def current(approval: Approval | None, inv: Invoice) -> Approval:
    """The approval only counts while the invoice is exactly what was approved."""
    if approval and approval.status == APPROVED and approval.fingerprint == fingerprint(inv):
        return approval
    return Approval(DRAFT)
