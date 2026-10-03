from datetime import date

import pytest

from reconciler.normalise import (aircraft_category, leg_of, load_mappings, parse_date,
                                  parse_time, service_of)

WEEK = (date(2026, 9, 12), date(2026, 9, 18))


# ---- times: anything that could be misread comes back None, never a guess ----

@pytest.mark.parametrize("raw", [
    "10",        # truncated: must NOT become 10:00
    "1010",      # no colon
    "10.5",
    "7:10",      # no am/pm: morning or evening?
    "24:00",
    "12:60",
    "13:00pm",
    "0:30am",
    "7:10 xm",
    "",
    None,
    "  ",
])
def test_ambiguous_or_malformed_times_are_unparseable(raw):
    assert parse_time(raw) is None


def test_end_time_10_is_not_ten_oclock():
    assert parse_time("10") != 10 * 60
    assert parse_time("10") is None


@pytest.mark.parametrize("raw,minutes", [
    ("06:40", 6 * 60 + 40),
    ("7:10am", 7 * 60 + 10),
    ("7:45am", 7 * 60 + 45),
    ("12:00am", 0),
    ("12:30pm", 12 * 60 + 30),
    ("1:05pm", 13 * 60 + 5),
    ("23:59", 23 * 60 + 59),
])
def test_clear_times_parse(raw, minutes):
    assert parse_time(raw) == minutes


# ---- dates: DD/MM ----

@pytest.mark.parametrize("raw,expected,year_missing", [
    ("12/09/2026", date(2026, 9, 12), False),
    ("14/09/26", date(2026, 9, 14), False),
    ("2026-09-12", date(2026, 9, 12), False),
    ("12-Sep", date(2026, 9, 12), True),
])
def test_dates(raw, expected, year_missing):
    assert parse_date(raw, *WEEK) == (expected, year_missing)


@pytest.mark.parametrize("raw", ["31/02/2026", "12-Foo", "12/13/2026", "", None, "12-Oct"])
def test_bad_or_out_of_window_dates_are_none(raw):
    assert parse_date(raw, *WEEK)[0] is None


# ---- mapping tables ----

def test_mappings():
    m = load_mappings()
    assert aircraft_category(m, "738") == ("Narrowbody", "verified")
    assert aircraft_category(m, " Boeing 737 ") == ("Narrowbody", "verified")
    assert aircraft_category(m, "320") == ("Narrowbody", "assumed")
    assert aircraft_category(m, "E190") is None
    assert aircraft_category(m, "") is None
    assert leg_of(m, "transit") == "transit"
    assert leg_of(m, "Terminator") == "terminating"
    assert leg_of(m, "T") == "ambiguous"
    assert leg_of(m, "") == "missing"
    assert service_of(m, "Push back") == "Push-back"
    assert service_of(m, "Lav Service") is None
