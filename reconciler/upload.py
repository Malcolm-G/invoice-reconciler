"""Read an uploaded job log or rate card (CSV or Excel) into the same raw, all-text rows the
bundled datasets use. Nothing is cleaned: values stay as exported. No Streamlit, no Claude here.

Excel cells that hold real dates or times are written out as plain text (YYYY-MM-DD, HH:MM).
An Excel time stored as a bare fraction (0.2916...) cannot be recovered; it is kept as that
number, which later reads as unparseable and holds the line rather than guessing.
"""
import csv
import io
from dataclasses import dataclass, field
from datetime import date, datetime, time

import config

LOG_COLUMNS = ["Date", "Flight", "Aircraft", "Transit/Term", "Service", "Start", "End", "Notes"]
LOG_REQUIRED = ["Date", "Service"]
RATE_COLUMNS = ["Service", "Aircraft Category", "Transit / Terminator", "Rate (AUD)"]

_LOG_ALIASES = {
    "date": "Date", "flight": "Flight", "aircraft": "Aircraft", "service": "Service",
    "start": "Start", "end": "End", "notes": "Notes", "note": "Notes",
    "transit/term": "Transit/Term", "transit/terminator": "Transit/Term",
    "transit/terminating": "Transit/Term", "transitterm": "Transit/Term",
}
_RATE_ALIASES = {
    "service": "Service", "aircraftcategory": "Aircraft Category", "category": "Aircraft Category",
    "transit/terminator": "Transit / Terminator", "transit/term": "Transit / Terminator",
    "rate(aud)": "Rate (AUD)", "rate": "Rate (AUD)",
}


class UploadError(Exception):
    """A problem the user can fix (shown in the UI). Never contains row contents."""


@dataclass
class Parsed:
    rows: list[dict]
    notices: list[str] = field(default_factory=list)


def _norm_header(h) -> str:
    return "".join(str(h or "").lower().split())


def _cell_text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.date().isoformat() if v.time() == time(0, 0) else v.strftime("%Y-%m-%d %H:%M")
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, time):
        return v.strftime("%H:%M")
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def _read_table(filename: str, data: bytes) -> list[list[str]]:
    name = (filename or "").lower()
    if name.endswith(".csv"):
        for enc in ("utf-8-sig", "cp1252"):
            try:
                text = data.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise UploadError("Could not read the file's text encoding.")
        return [[c.strip() for c in row] for row in csv.reader(io.StringIO(text, newline=""))]
    if name.endswith((".xlsx", ".xlsm")):
        import openpyxl
        try:
            wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        except Exception as e:  # corrupt or password-protected workbook
            raise UploadError("Could not open the Excel file. It may be corrupt or password-protected.") from e
        ws = wb.worksheets[0]
        return [[_cell_text(c) for c in row] for row in ws.iter_rows(values_only=True)]
    raise UploadError("Unsupported file type. Upload a .csv or .xlsx file.")


def _parse(filename: str, data: bytes, aliases: dict, columns: list[str], required: list[str],
           max_rows: int, what: str) -> Parsed:
    table = _read_table(filename, data)
    table = [r for r in table if any(c.strip() for c in r)]
    if not table:
        raise UploadError(f"The {what} file is empty.")
    header, body = table[0], table[1:]
    index: dict[str, int] = {}
    for i, h in enumerate(header):
        canon = aliases.get(_norm_header(h))
        if canon and canon not in index:
            index[canon] = i
    missing_required = [c for c in required if c not in index]
    if missing_required:
        raise UploadError(f"The {what} file is missing required column(s): {', '.join(missing_required)}. "
                          f"Expected columns: {', '.join(columns)}.")
    notices = []
    absent = [c for c in columns if c not in index]
    if absent:
        notices.append(f"Column(s) not found, treated as blank: {', '.join(absent)}.")
    ignored = [h for h in header if aliases.get(_norm_header(h)) is None and str(h).strip()]
    if ignored:
        notices.append(f"Ignored column(s): {', '.join(str(h) for h in ignored)}.")
    if len(body) > max_rows:
        raise UploadError(f"The {what} file has {len(body)} rows; the limit is {max_rows}.")
    rows = []
    for r in body:
        rows.append({c: (r[index[c]].strip() if c in index and index[c] < len(r) else "") for c in columns})
    return Parsed(rows, notices)


def parse_log(filename: str, data: bytes, max_rows: int | None = None) -> Parsed:
    parsed = _parse(filename, data, _LOG_ALIASES, LOG_COLUMNS, LOG_REQUIRED,
                    max_rows or config.MAX_UPLOAD_ROWS, "job log")
    if not parsed.rows:
        raise UploadError("The job log file has a header but no rows.")
    for i, row in enumerate(parsed.rows, start=1):
        row["row_id"] = i
    return parsed


def parse_rate_card(filename: str, data: bytes) -> Parsed:
    parsed = _parse(filename, data, _RATE_ALIASES, RATE_COLUMNS, RATE_COLUMNS, 200, "rate card")
    if not parsed.rows:
        raise UploadError("The rate card file has a header but no rows.")
    return parsed


def suggest_period(rows: list[dict]) -> tuple[date, date] | None:
    """Earliest and latest date among rows whose date text contains a year; None if there are none."""
    from reconciler.normalise import parse_date
    far = date(2000, 1, 1), date(2100, 12, 31)
    days = []
    for r in rows:
        d, year_missing = parse_date(r.get("Date"), *far)
        if d is not None and not year_missing:
            days.append(d)
    return (min(days), max(days)) if days else None
