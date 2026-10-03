from decimal import Decimal

from reconciler.loader import load_dataset
from reconciler.models import Hold
from reconciler.normalise import load_mappings
from reconciler.pricing import find_rate, load_rates, parse_rate_cell, prorata_amount


def rates():
    return load_rates(load_dataset("synthetic").rate_rows, load_mappings())


def test_rate_cells():
    assert parse_rate_cell("180") == (Decimal("180"), None, None)
    assert parse_rate_cell("75 per 15 min (pro-rata)") == (None, 15, Decimal("75"))
    assert parse_rate_cell("call us") == (None, None, None)


def test_exact_match():
    r = find_rate(rates(), "Push-back", "Narrowbody", "transit", False)
    assert r.rate and r.rate.flat == Decimal("150")


def test_any_matches_any_value():
    r = find_rate(rates(), "Ground Power Unit (GPU)", None, "transit", True)
    assert r.rate and r.rate.flat == Decimal("55")


def test_no_nearest_rate():
    # Push-back is priced for transit only. Terminating has NO rate; widebody price is not borrowed.
    r = find_rate(rates(), "Push-back", "Widebody", "terminating", False)
    assert r.rate is None and r.hold.code == Hold.NO_RATE_LEG


def test_originating_has_no_rate():
    r = find_rate(rates(), "Cabin Clean", "Narrowbody", "originating", False)
    assert r.rate is None and r.hold.code == Hold.NO_RATE_LEG


def test_unknown_service():
    r = find_rate(rates(), None, "Narrowbody", "terminating", False)
    assert r.rate is None and r.hold.code == Hold.NO_RATE_SERVICE


def test_gaps_that_change_price_hold():
    assert find_rate(rates(), "Baggage Handling", "Narrowbody", "ambiguous", False).hold.code == Hold.AMBIGUOUS_LEG
    assert find_rate(rates(), "Baggage Handling", "Narrowbody", "missing", False).hold.code == Hold.MISSING_LEG
    assert find_rate(rates(), "Cabin Clean", None, "terminating", True).hold.code == Hold.MISSING_AIRCRAFT
    assert find_rate(rates(), "Cabin Clean", None, "terminating", False).hold.code == Hold.UNKNOWN_AIRCRAFT


def test_prorata_is_per_minute_not_blocks():
    deicing = find_rate(rates(), "De-icing", "Narrowbody", "terminating", False).rate
    # synthetic card: 60 per 15 min = 4.00/min. 38 min = 152.00 (3 whole blocks would be 180).
    assert prorata_amount(deicing, 38) == Decimal("152.00")
    assert prorata_amount(deicing, 38) != Decimal("180.00")
    assert prorata_amount(deicing, 15) == Decimal("60.00")


def test_prorata_rounds_to_the_cent():
    from reconciler.pricing import RateEntry
    odd = RateEntry("De-icing", "Any", "Any", None, 15, Decimal("70"))
    assert prorata_amount(odd, 1) == Decimal("4.67")  # 70/15 = 4.6667
