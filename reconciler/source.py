"""Decide where this run's extractions come from, and say so plainly. No network calls here."""
from dataclasses import dataclass

from reconciler.cache import load_cache
from reconciler.fixtures import FIXTURE_NOTE, load_fixture_extractions
from reconciler.loader import Dataset


@dataclass(frozen=True)
class Source:
    kind: str      # "cached" | "fixture"
    banner: str    # shown at the top of the UI


def resolve_extractions(ds: Dataset):
    """Return (extractions, Source). Recorded Claude results if a cache exists, else labelled fixtures."""
    cached, info = load_cache(ds.name, ds.log_rows, ds.period_start, ds.period_end)
    if cached is not None:
        n_ok = sum(1 for e, _ in cached.values() if e is not None)
        banner = (f"CACHED RESULTS. These are Claude's outputs recorded on {info.recorded_at} with model "
                  f"{info.model} (prompt {info.prompt_version}). No API call is being made. "
                  f"{n_ok} of {len(cached)} rows have a cached result; any others are held.")
        return cached, Source("cached", banner)
    return (load_fixture_extractions(ds.name, len(ds.log_rows)),
            Source("fixture", "NOT CLAUDE OUTPUT. " + FIXTURE_NOTE + " Record real results with python -m reconciler.record."))
