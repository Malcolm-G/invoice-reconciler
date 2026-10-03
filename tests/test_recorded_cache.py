"""The committed synthetic cache holds real recorded Claude outputs. Replaying it must reproduce the
expected invoice with no network and no API key."""
import os
from decimal import Decimal

from reconciler.checks import run_checks
from reconciler.invoice import build_invoice
from reconciler.loader import load_dataset
from reconciler.models import Tier
from reconciler.source import resolve_extractions


def test_recorded_synthetic_cache_replays_to_expected_invoice(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    ds = load_dataset("synthetic")
    extractions, source = resolve_extractions(ds)
    assert source.kind == "cached" and "answers Claude gave earlier" in source.banner
    inv = build_invoice(ds, extractions)
    assert inv.draft_total == Decimal("1332.00")
    assert inv.tier_counts[Tier.duplicate] == 1 and inv.tier_counts[Tier.held] == 7
    assert all(c.passed for c in run_checks(inv))


def test_no_secret_in_tracked_text_files():
    from pathlib import Path
    import config
    for path in config.ROOT.rglob("*"):
        if path.is_dir() or ".venv" in path.parts or ".git" in path.parts or path.name == ".env" \
                or path.suffix in (".pyc",) or "tests_private" in path.parts or "sample" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        assert ("sk-" + "ant-") not in text, path  # split so this file does not match itself
