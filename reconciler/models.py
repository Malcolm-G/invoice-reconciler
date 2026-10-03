"""Data shapes. RowExtraction is what Claude returns; it has no price or total fields."""
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, field_validator


# ---------- Claude's output (validated; any failure holds the row) ----------

class LegType(str, Enum):
    transit = "transit"
    terminating = "terminating"
    originating = "originating"
    ambiguous = "ambiguous"
    missing = "missing"


class NoteKind(str, Enum):
    none = "none"
    restates_gap = "restates_gap"
    restates_unpriced = "restates_unpriced"
    requests_confirmation = "requests_confirmation"
    questions_line = "questions_line"
    contradicts_line = "contradicts_line"
    aircraft_change = "aircraft_change"
    other = "other"


class FlagType(str, Enum):
    ambiguous_abbreviation = "ambiguous_abbreviation"
    missing_value = "missing_value"
    unparseable_value = "unparseable_value"
    impossible_time_range = "impossible_time_range"
    unknown_aircraft_code = "unknown_aircraft_code"
    unfamiliar_service = "unfamiliar_service"
    note_needs_attention = "note_needs_attention"
    other_uncertainty = "other_uncertainty"


class Flag(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: FlagType
    reason: str
    assumption: str | None = None

    @field_validator("reason")
    @classmethod
    def _reason_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("reason must not be empty")
        return v


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class RowExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    row_id: int
    date_iso: str | None
    date_year_missing: bool
    flight: str | None
    aircraft_as_logged: str | None
    leg_type: LegType
    service_as_logged: str | None
    start_time: str | None
    end_time: str | None
    note_kind: NoteKind
    note_summary: str | None = None
    flags: list[Flag] = []

    @field_validator("date_iso")
    @classmethod
    def _date_format(cls, v):
        if v is not None and not _DATE_RE.match(v):
            raise ValueError("date_iso must be YYYY-MM-DD or null")
        return v

    @field_validator("start_time", "end_time")
    @classmethod
    def _time_format(cls, v):
        if v is not None and not _TIME_RE.match(v):
            raise ValueError("time must be HH:MM (24h) or null")
        return v


# ---------- Hold reasons (stable codes; the exceptions routing table keys on these) ----------

class Hold(str, Enum):
    EXTRACTION_INVALID = "EXTRACTION_INVALID"
    EXTRACTION_MISMATCH = "EXTRACTION_MISMATCH"
    DATE_UNRESOLVED = "DATE_UNRESOLVED"
    AMBIGUOUS_LEG = "AMBIGUOUS_LEG"
    MISSING_LEG = "MISSING_LEG"
    UNKNOWN_AIRCRAFT = "UNKNOWN_AIRCRAFT"
    MISSING_AIRCRAFT = "MISSING_AIRCRAFT"
    NO_RATE_SERVICE = "NO_RATE_SERVICE"
    NO_RATE_LEG = "NO_RATE_LEG"
    RATE_UNUSABLE = "RATE_UNUSABLE"
    DURATION_NEEDED = "DURATION_NEEDED"
    IMPOSSIBLE_TIME = "IMPOSSIBLE_TIME"
    NOTE_NEEDS_ATTENTION = "NOTE_NEEDS_ATTENTION"
    EXTRACTOR_FLAG = "EXTRACTOR_FLAG"


class Tier(str, Enum):
    firm = "firm"
    assumed = "assumed"
    held = "held"
    duplicate = "duplicate"


@dataclass(frozen=True)
class HoldReason:
    code: Hold
    text: str


@dataclass
class PricedLine:
    row_id: int
    raw: dict
    tier: Tier
    amount: Decimal = Decimal("0.00")
    line_date: date | None = None
    flight: str = ""
    aircraft: str = ""
    leg: str = ""
    service: str = ""
    rate_applied: str = ""
    notes: list[str] = field(default_factory=list)       # one-line note per judgment call
    assumption: str | None = None                          # shown on assumed lines
    holds: list[HoldReason] = field(default_factory=list)
    duplicate_of: int | None = None
