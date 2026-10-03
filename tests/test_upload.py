import io
from datetime import date, datetime, time
from decimal import Decimal

import openpyxl
import pytest

import config
from reconciler.export import invoice_csv
from reconciler.fixtures import load_fixture_extractions
from reconciler.invoice import build_invoice
from reconciler.loader import Dataset, load_dataset
from reconciler.upload import (LOG_COLUMNS, UploadError, parse_log, parse_rate_card, suggest_period)

SYN = config.dataset_dir("synthetic")


def xlsx_bytes(rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---- CSV ----

def test_bundled_csv_round_trips_exactly():
    ds = load_dataset("synthetic")
    parsed = parse_log("job_log.csv", (SYN / "job_log.csv").read_bytes())
    assert parsed.rows == ds.log_rows                      # raw values and row_ids identical
    assert parse_rate_card("rate_card.csv", (SYN / "rate_card.csv").read_bytes()).rows == ds.rate_rows


def test_uploaded_file_produces_the_same_invoice_as_the_bundled_dataset():
    log = parse_log("job_log.csv", (SYN / "job_log.csv").read_bytes())
    rates = parse_rate_card("rate_card.csv", (SYN / "rate_card.csv").read_bytes())
    ds = Dataset("upload", "x", "2026-11-02", "2026-11-08", log.rows, rates.rows)
    inv = build_invoice(ds, load_fixture_extractions("synthetic", len(ds.log_rows)))
    assert inv.draft_total == Decimal("1332.00")


def test_headers_are_matched_loosely_and_extras_ignored():
    data = b"  DATE ,flight,Service,Transit/Terminator,Colour\n12/09/2026,QF1,Push-back,Transit,red\n"
    p = parse_log("x.csv", data)
    assert p.rows[0]["Date"] == "12/09/2026" and p.rows[0]["Transit/Term"] == "Transit"
    assert p.rows[0]["Aircraft"] == "" and p.rows[0]["row_id"] == 1
    assert any("Ignored" in n and "Colour" in n for n in p.notices)
    assert any("treated as blank" in n for n in p.notices)


def test_values_are_not_cleaned():
    p = parse_log("x.csv", b"Date,Service,End\n12-Sep,Push back,10\n")
    assert p.rows[0]["Date"] == "12-Sep" and p.rows[0]["Service"] == "Push back" and p.rows[0]["End"] == "10"


def test_blank_rows_skipped_and_cp1252_accepted():
    p = parse_log("x.csv", "Date,Service,Notes\n12/09/2026,Push-back,caf\xe9\n,,\n".encode("cp1252"))
    assert len(p.rows) == 1 and p.rows[0]["Notes"] == "café"


@pytest.mark.parametrize("name,data,msg", [
    ("x.csv", b"", "empty"),
    ("x.csv", b"Flight,Aircraft\nQF1,B737\n", "missing required"),
    ("x.csv", b"Date,Service\n", "no rows"),
    ("x.pdf", b"%PDF", "Unsupported"),
    ("x.xlsx", b"not a workbook", "Excel"),
])
def test_bad_files_give_clear_errors(name, data, msg):
    with pytest.raises(UploadError, match=msg):
        parse_log(name, data)


def test_row_cap():
    body = "Date,Service\n" + "12/09/2026,Push-back\n" * (config.MAX_UPLOAD_ROWS + 1)
    with pytest.raises(UploadError, match="limit"):
        parse_log("x.csv", body.encode())
    assert len(parse_log("x.csv", body.encode(), max_rows=config.MAX_UPLOAD_ROWS + 1).rows) == config.MAX_UPLOAD_ROWS + 1


def test_rate_card_needs_all_columns():
    with pytest.raises(UploadError, match="missing required"):
        parse_rate_card("r.csv", b"Service,Rate\nPush-back,180\n")


# ---- Excel ----

def test_excel_dates_times_and_numbers_become_plain_text():
    data = xlsx_bytes([
        ["Date", "Flight", "Aircraft", "Transit/Term", "Service", "Start", "End", "Notes"],
        [datetime(2026, 9, 12), "QF481", "B737", "Transit", "Push-back", time(6, 40), time(6, 55), None],
        [date(2026, 9, 13), "QF489", None, "Transit", "GPU", "09:00", 10.0, "x"],
    ])
    rows = parse_log("log.xlsx", data).rows
    assert rows[0]["Date"] == "2026-09-12" and rows[0]["Start"] == "06:40" and rows[0]["End"] == "06:55"
    assert rows[0]["Notes"] == "" and rows[1]["Aircraft"] == ""
    assert rows[1]["End"] == "10"            # a bare number stays "10", which the pipeline reads as unreadable


def test_excel_rate_card():
    data = xlsx_bytes([["Service", "Aircraft Category", "Transit / Terminator", "Rate (AUD)"],
                       ["Push-back", "Narrowbody", "Transit", 180], ["De-icing", "Any", "Any", "75 per 15 min (pro-rata)"]])
    rows = parse_rate_card("r.xlsx", data).rows
    assert rows[0]["Rate (AUD)"] == "180" and rows[1]["Rate (AUD)"] == "75 per 15 min (pro-rata)"


def test_period_suggestion_ignores_year_less_dates():
    rows = [{"Date": "12/09/2026"}, {"Date": "12-Sep"}, {"Date": "18/09/2026"}, {"Date": "junk"}]
    assert suggest_period(rows) == (date(2026, 9, 12), date(2026, 9, 18))
    assert suggest_period([{"Date": "12-Sep"}]) is None


# ---- export ----

def test_csv_export_neutralises_formulas_and_includes_total():
    ds = load_dataset("synthetic")
    ds.log_rows[0]["Flight"] = "=HYPERLINK(\"http://x\")"
    inv = build_invoice(ds, load_fixture_extractions("synthetic", len(ds.log_rows)))
    out = invoice_csv(inv)
    assert "'=HYPERLINK" in out and "\n=HYPERLINK" not in out and ",=HYPERLINK" not in out
    assert "DRAFT TOTAL" in out
    ds.log_rows[0]["Flight"] = "XA201"
