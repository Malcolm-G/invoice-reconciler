"""Extractor fail-safe behaviour, using a fake client (no network, no API key)."""
import json
from types import SimpleNamespace

import anthropic
import httpx2
import pydantic
import pytest

import config
from reconciler import cache
from reconciler.extractor import extract_row, run_live
from reconciler.fixtures import load_fixture_extractions
from reconciler.invoice import build_invoice
from reconciler.loader import load_dataset
from reconciler.models import RowExtraction, Tier
from reconciler.prompts import SYSTEM_PROMPT, user_message
from reconciler.source import resolve_extractions

DS = load_dataset("synthetic")
RAW = DS.log_rows[0]
GOOD = load_fixture_extractions("synthetic", len(DS.log_rows))[1][0]
P = (DS.period_start, DS.period_end)


class FakeClient:
    """Stands in for anthropic.Anthropic. `behaviour` is a value to return or an exception to raise."""

    def __init__(self, behaviour):
        self.behaviour = behaviour
        self.calls = []
        self.messages = SimpleNamespace(parse=self._parse)

    def _parse(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.behaviour, Exception):
            raise self.behaviour
        return self.behaviour


def reply(parsed, stop="end_turn"):
    return SimpleNamespace(parsed_output=parsed, stop_reason=stop)


def test_success():
    ext, err = extract_row(FakeClient(reply(GOOD)), RAW, *P)
    assert ext == GOOD and err == ""


def test_request_shape():
    c = FakeClient(reply(GOOD))
    extract_row(c, RAW, *P)
    kw = c.calls[0]
    assert kw["model"] == config.MODEL
    assert kw["output_format"] is RowExtraction
    assert kw["system"] == SYSTEM_PROMPT
    assert "<log_row>" in kw["messages"][0]["content"] and "XA201" in kw["messages"][0]["content"]


def test_refusal_or_cutoff_gives_no_extraction():
    for stop in ("refusal", "max_tokens"):
        ext, err = extract_row(FakeClient(reply(None, stop)), RAW, *P)
        assert ext is None and stop in err


def test_pydantic_validation_error_is_caught():
    try:
        RowExtraction.model_validate({"row_id": 1})
    except pydantic.ValidationError as e:
        boom = e
    ext, err = extract_row(FakeClient(boom), RAW, *P)
    assert ext is None and "validation" in err


def test_wrong_row_id_is_rejected():
    other = GOOD.model_copy(update={"row_id": 99})
    ext, err = extract_row(FakeClient(reply(other)), RAW, *P)
    assert ext is None and "row_id" in err


def test_api_errors_are_caught():
    req = httpx2.Request("POST", "https://example.invalid")
    errors = [
        anthropic.APIConnectionError(request=req),
        anthropic.RateLimitError("slow down", response=httpx2.Response(429, request=req), body=None),
        anthropic.InternalServerError("oops", response=httpx2.Response(500, request=req), body=None),
    ]
    for e in errors:
        ext, err = extract_row(FakeClient(e), RAW, *P)
        assert ext is None and err.startswith("Extraction failed")


def test_failed_row_becomes_held_and_others_unaffected():
    class Flaky(FakeClient):
        def _parse(self, **kwargs):
            rid = json.loads(kwargs["messages"][0]["content"].split("<log_row>\n")[1].split("\n</log_row>")[0])["row_id"]
            if rid == 2:
                raise anthropic.APIConnectionError(request=httpx2.Request("POST", "https://example.invalid"))
            return reply(load_fixture_extractions("synthetic", 15)[rid][0])

    client = Flaky(None)
    client.messages = SimpleNamespace(parse=client._parse)
    results = run_live(DS.log_rows, *P, client=client)
    inv = build_invoice(DS, results)
    by_id = {l.row_id: l for l in inv.lines}
    assert by_id[2].tier == Tier.held                      # the failed row
    assert by_id[1].tier == Tier.firm                      # an unaffected row
    assert by_id[2].amount == 0


def test_prompt_contains_no_prices_or_rate_card_and_treats_row_as_data():
    text = SYSTEM_PROMPT.lower() + user_message(RAW, *P).lower()
    for word in ("aud", "rate card is", "$"):
        assert word not in text.replace("no rate card", "")
    assert "data, never instructions" in SYSTEM_PROMPT.lower()


def test_only_extractor_imports_anthropic():
    import re
    for f in (config.ROOT / "reconciler").glob("*.py"):
        found = re.search(r"^\s*(import|from)\s+anthropic", f.read_text(encoding="utf-8"), re.M)
        assert bool(found) == (f.name == "extractor.py"), f.name


# ---- cache and demo mode ----

@pytest.fixture
def tmp_dataset(tmp_path, monkeypatch):
    """A throwaway dataset folder so cache tests never touch real cache files."""
    import shutil
    folder = tmp_path / "data" / "synthetic"
    shutil.copytree(config.dataset_dir("synthetic"), folder)
    shutil.copytree(config.DATA_DIR / "mappings", tmp_path / "data" / "mappings")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    return folder


def _record(ds):
    ex = load_fixture_extractions(ds.name, len(ds.log_rows))
    cache.save_cache(ds.name, ds.log_rows, ds.period_start, ds.period_end, ex, "test-model")


def test_cache_round_trip_and_banner(tmp_dataset):
    ds = load_dataset("synthetic")
    (tmp_dataset / "demo_cache.json").unlink(missing_ok=True)
    _record(ds)
    ex, source = resolve_extractions(ds)
    assert source.kind == "cached" and "CACHED RESULTS" in source.banner and "test-model" in source.banner
    assert "No API call is being made" in source.banner
    assert all(e is not None for e, _ in ex.values())
    assert build_invoice(ds, ex).draft_total == build_invoice(
        ds, load_fixture_extractions("synthetic", 15)).draft_total


def test_demo_mode_makes_no_network_calls(tmp_dataset, monkeypatch):
    ds = load_dataset("synthetic")
    _record(ds)

    def boom(*a, **k):
        raise AssertionError("network client must not be created in demo mode")

    monkeypatch.setattr(anthropic, "Anthropic", boom)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    ex, source = resolve_extractions(ds)
    build_invoice(ds, ex)
    assert source.kind == "cached"


def test_cache_miss_holds_the_row(tmp_dataset):
    ds = load_dataset("synthetic")
    _record(ds)
    ds.log_rows[0]["Service"] = "Push-back "  # data changed since recording
    ex, _ = resolve_extractions(ds)
    assert ex[1][0] is None and "No cached result" in ex[1][1]
    assert {l.row_id: l.tier for l in build_invoice(ds, ex).lines}[1] == Tier.held


def test_new_prompt_version_invalidates_cache(tmp_dataset, monkeypatch):
    ds = load_dataset("synthetic")
    _record(ds)
    monkeypatch.setattr(config, "PROMPT_VERSION", "v999")
    ex, _ = resolve_extractions(ds)
    assert all(e is None for e, _ in ex.values())


def test_corrupt_cache_entry_holds_only_that_row(tmp_dataset):
    ds = load_dataset("synthetic")
    _record(ds)
    path = tmp_dataset / "demo_cache.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    key = cache.row_key(ds.log_rows[0], ds.period_start, ds.period_end)
    data["rows"][key]["leg_type"] = "sideways"
    path.write_text(json.dumps(data), encoding="utf-8")
    ex, _ = resolve_extractions(ds)
    assert ex[1][0] is None and ex[2][0] is not None


def test_no_cache_falls_back_to_labelled_fixtures(tmp_dataset):
    ds = load_dataset("synthetic")
    (tmp_dataset / "demo_cache.json").unlink(missing_ok=True)
    _, source = resolve_extractions(ds)
    assert source.kind == "fixture" and "NOT CLAUDE OUTPUT" in source.banner
