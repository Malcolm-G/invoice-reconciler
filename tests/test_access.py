from types import SimpleNamespace

from reconciler.access import live_access, session_budget_left
from reconciler.extractor import run_live
from reconciler.fixtures import load_fixture_extractions
from reconciler.loader import load_dataset
from reconciler.models import Tier
from reconciler.invoice import build_invoice

KEY = {"ANTHROPIC_API_KEY": "k"}


def test_no_key_means_no_live_use():
    assert not live_access("anything", env={}).allowed
    assert not live_access("p", env={"APP_PASSCODE": "p"}).allowed


def test_key_without_passcode_fails_closed():
    a = live_access("", env=KEY)
    assert not a.allowed and "isn't switched on" in a.reason


def test_passcode_required_and_checked():
    env = {**KEY, "APP_PASSCODE": "letmein"}
    assert live_access("", env=env).needs_passcode and not live_access("", env=env).allowed
    assert live_access("wrong", env=env).reason == "That passcode isn't right."
    assert live_access("letmein", env=env).allowed


def test_open_live_is_explicit_opt_in():
    assert live_access("", env={**KEY, "ALLOW_OPEN_LIVE": "1"}).allowed
    assert not live_access("", env={**KEY, "ALLOW_OPEN_LIVE": "yes"}).allowed


def test_session_budget():
    assert session_budget_left(100, 50, 150)
    assert not session_budget_left(100, 51, 150)


def test_concurrent_run_keeps_row_order_and_isolates_failures():
    ds = load_dataset("synthetic")
    fixtures = load_fixture_extractions("synthetic", len(ds.log_rows))

    def parse(**kw):
        import json
        rid = json.loads(kw["messages"][0]["content"].split("<log_row>\n")[1].split("\n</log_row>")[0])["row_id"]
        if rid == 2:
            raise RuntimeError("boom")             # an unexpected error must stay on its own row
        return SimpleNamespace(parsed_output=fixtures[rid][0], stop_reason="end_turn")

    seen = []
    client = SimpleNamespace(messages=SimpleNamespace(parse=parse))
    res = run_live(ds.log_rows, ds.period_start, ds.period_end, client=client, workers=5,
                   on_progress=lambda d, t: seen.append((d, t)))
    assert list(res) == [r["row_id"] for r in ds.log_rows]
    assert res[2][0] is None and "RuntimeError" in res[2][1]
    assert res[1][0] is not None
    assert seen[-1] == (15, 15)
    inv = build_invoice(ds, res)
    assert {l.row_id: l.tier for l in inv.lines}[2] == Tier.held
