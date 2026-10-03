"""Hand-written extraction fixtures (S1). NOT Claude output.

Read from data/<dataset>/extractions_fixture.json. Each entry is validated; an
invalid entry becomes (None, error) and the row is held, same as a bad Claude reply.
"""
import json

import config
from pydantic import ValidationError

from reconciler.models import RowExtraction

FIXTURE_NOTE = "Hand-written fixtures for development. These are NOT Claude outputs."


def load_fixture_extractions(dataset: str, n_rows: int) -> dict[int, tuple[RowExtraction | None, str]]:
    path = config.dataset_dir(dataset) / "extractions_fixture.json"
    items = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    out: dict[int, tuple[RowExtraction | None, str]] = {}
    for item in items:
        rid = item.get("row_id") if isinstance(item, dict) else None
        try:
            out[int(rid)] = (RowExtraction.model_validate(item), "")
        except (ValidationError, TypeError, ValueError):
            if isinstance(rid, int):
                out[rid] = (None, "Extraction failed validation.")
    for rid in range(1, n_rows + 1):
        out.setdefault(rid, (None, "No extraction available for this row."))
    return out
