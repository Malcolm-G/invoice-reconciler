"""Per-dataset cache of Claude's extractions (data/<dataset>/demo_cache.json).

Only validated extractions are stored. A cached entry is used only if its key
matches the current raw row, batch week and prompt version, so edited data or a
new prompt never silently reuses stale results. No Claude dependency here.
"""
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone

import config
from pydantic import ValidationError

from reconciler.models import RowExtraction

RAW_COLUMNS = ("Date", "Flight", "Aircraft", "Transit/Term", "Service", "Start", "End", "Notes")


def row_key(raw: dict, period_start: str, period_end: str) -> str:
    payload = json.dumps(
        {"row": {c: raw.get(c) or "" for c in RAW_COLUMNS}, "period": [period_start, period_end],
         "prompt": config.PROMPT_VERSION},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


@dataclass(frozen=True)
class CacheInfo:
    model: str
    prompt_version: str
    recorded_at: str


def cache_path(dataset: str):
    return config.dataset_dir(dataset) / "demo_cache.json"


def load_cache(dataset: str, rows: list[dict], period_start: str, period_end: str):
    """Return (extractions, info). extractions: row_id -> (RowExtraction | None, error text).
    info is None if there is no cache file. Rows without a matching entry become held-row errors."""
    path = cache_path(dataset)
    if not path.exists():
        return None, None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        entries = data["rows"]
        info = CacheInfo(data["model"], data["prompt_version"], data["recorded_at"])
    except (ValueError, KeyError, TypeError):
        return None, None
    out = {}
    for raw in rows:
        entry = entries.get(row_key(raw, period_start, period_end))
        if entry is None:
            out[raw["row_id"]] = (None, "No recorded answer for this row (the data or instructions changed since it was recorded).")
            continue
        try:
            ext = RowExtraction.model_validate(entry)
            out[raw["row_id"]] = (ext, "") if ext.row_id == raw["row_id"] else (None, "The recorded answer is for a different row.")
        except ValidationError:
            out[raw["row_id"]] = (None, "The recorded answer for this row wasn't usable.")
    return out, info


def save_cache(dataset: str, rows: list[dict], period_start: str, period_end: str,
               extractions: dict, model: str) -> None:
    entries = {}
    for raw in rows:
        ext, _ = extractions.get(raw["row_id"], (None, ""))
        if ext is not None:
            entries[row_key(raw, period_start, period_end)] = ext.model_dump(mode="json")
    payload = {
        "model": model,
        "prompt_version": config.PROMPT_VERSION,
        "recorded_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "rows": entries,
    }
    cache_path(dataset).write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
