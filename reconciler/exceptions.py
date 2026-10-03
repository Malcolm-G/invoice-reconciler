"""Exceptions queue: one drafted question per held line, grouped by owner. Plain code, no Claude.

Questions come from fixed templates keyed on the hold reason, so they can only ask about facts
the code already knows are uncertain. Owners come from data/mappings/routing.csv, which is an
ASSUMPTION about who would answer; it is labelled that way in the UI. Questions are shown for
a person to review; this module does nothing else with them.
"""
import csv
from dataclasses import dataclass

import config
from reconciler.invoice import Invoice
from reconciler.models import Hold, PricedLine

TEMPLATES: dict[Hold, str] = {
    Hold.AMBIGUOUS_LEG: "The log says \"{leg}\" for transit/terminating. Was this a transit, a terminating flight or an originating flight?",
    Hold.MISSING_LEG: "The transit/terminating field is blank. Was this a transit, a terminating flight or an originating flight?",
    Hold.UNKNOWN_AIRCRAFT: "The aircraft code \"{aircraft}\" is not recognised. Which aircraft type was it, and is it narrowbody or widebody?",
    Hold.MISSING_AIRCRAFT: "The aircraft type is missing. Which aircraft type was it, and is it narrowbody or widebody?",
    Hold.IMPOSSIBLE_TIME: "The start time \"{start}\" and end time \"{end}\" do not make a valid range. What were the correct times?",
    Hold.DURATION_NEEDED: "The price depends on duration, but the start time (\"{start}\") or end time (\"{end}\") is missing or unreadable. What were the times?",
    Hold.DATE_UNRESOLVED: "The date \"{date}\" could not be placed in the batch week. What was the correct date?",
    Hold.NOTE_NEEDS_ATTENTION: "The log note says: \"{note}\". Does this change what should be billed for this line, and if so how?",
    Hold.NO_RATE_SERVICE: "\"{service}\" is not on the price list, so there is no agreed price. Is there an agreed price for it, and what is it?",
    Hold.NO_RATE_LEG: "The price list has no agreed price for {service} when logged as \"{leg}\". Is the logged transit/terminating value correct, and if so, is there an agreed price?",
    Hold.RATE_UNUSABLE: "The price list entry for {service} could not be read. What is the agreed price?",
    Hold.EXTRACTION_MISMATCH: "Please check this row. {detail}",
    Hold.EXTRACTION_INVALID: "Claude couldn't read this row. Please check its values.",
    Hold.EXTRACTOR_FLAG: "{detail} Please review the row.",
}


@dataclass(frozen=True)
class Question:
    row_id: int
    owner: str
    text: str
    context: str      # "date | flight | service" for display
    other_reasons: tuple[str, ...]   # other, genuinely different reasons the line is held


def load_routing() -> dict[Hold, tuple[str, int]]:
    path = config.DATA_DIR / "mappings" / "routing.csv"
    with path.open(newline="", encoding="utf-8-sig") as f:
        return {Hold(r["hold_code"]): (r["owner"], int(r["priority"])) for r in csv.DictReader(f)}


def _fill(template: str, line: PricedLine, detail: str) -> str:
    raw = line.raw
    values = {
        "leg": (raw.get("Transit/Term") or "").strip() or "(blank)",
        "aircraft": (raw.get("Aircraft") or "").strip() or "(blank)",
        "start": (raw.get("Start") or "").strip() or "(blank)",
        "end": (raw.get("End") or "").strip() or "(blank)",
        "date": (raw.get("Date") or "").strip() or "(blank)",
        "note": (raw.get("Notes") or "").strip(),
        "service": (raw.get("Service") or "").strip() or "(blank)",
        "detail": detail,
    }
    return template.format(**values)


def draft_questions(inv: Invoice) -> list[Question]:
    routing = load_routing()
    out = []
    for line in inv.held:
        # The hold with the lowest priority number leads: facts from operations come before rate questions.
        lead = min(line.holds, key=lambda h: routing[h.code][1])
        owner = routing[lead.code][0]
        # A Claude flag that merely repeats a problem the code already found is not a separate reason.
        has_code_reason = any(h.code != Hold.EXTRACTOR_FLAG for h in line.holds)
        others = tuple(h.text for h in line.holds
                       if h is not lead and not (h.code == Hold.EXTRACTOR_FLAG and has_code_reason))
        text = _fill(TEMPLATES[lead.code], line, lead.text)
        context = " | ".join(filter(None, [(line.raw.get("Date") or "").strip(), line.flight, line.service]))
        out.append(Question(line.row_id, owner, text, context, others))
    return out


def group_by_owner(questions: list[Question]) -> dict[str, list[Question]]:
    groups: dict[str, list[Question]] = {}
    for q in questions:
        groups.setdefault(q.owner, []).append(q)
    return dict(sorted(groups.items()))
