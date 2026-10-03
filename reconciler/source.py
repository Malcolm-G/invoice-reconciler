"""Decide where this run's extractions come from, and say so plainly. No network calls here."""
from dataclasses import dataclass
from datetime import datetime

import config
from reconciler.cache import load_cache
from reconciler.fixtures import load_fixture_extractions
from reconciler.loader import Dataset


@dataclass(frozen=True)
class Source:
    kind: str      # "cached" | "fixture"
    banner: str    # shown at the top of the UI, in plain language


def _nice_date(recorded_at: str) -> str:
    try:
        d = datetime.strptime(recorded_at, "%Y-%m-%d %H:%M UTC")
        return f"{d.day} {d.strftime('%b %Y')}"
    except ValueError:
        return recorded_at


def resolve_extractions(ds: Dataset):
    """Return (extractions, Source). Recorded Claude results if a cache exists, else labelled hand-written ones."""
    cached, info = load_cache(ds.name, ds.log_rows, ds.period_start, ds.period_end)
    if cached is not None:
        missing = sum(1 for e, _ in cached.values() if e is None)
        model = config.MODEL_LABELS.get(info.model, info.model)
        banner = (f"Demo: these are answers Claude gave earlier (recorded {_nice_date(info.recorded_at)}, {model}). "
                  "Nothing is being read live right now.")
        if missing:
            banner += (f" {missing} row{'s' if missing != 1 else ''} had no recorded answer "
                       "and are marked as needing a person.")
        return cached, Source("cached", banner)
    return (load_fixture_extractions(ds.name, len(ds.log_rows)),
            Source("fixture", "Test mode: these answers were written by hand, not by Claude."))
