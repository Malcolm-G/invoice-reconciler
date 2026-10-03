"""Read a dataset's CSVs exactly as exported. No cleaning happens here."""
import csv
import json
from dataclasses import dataclass
from pathlib import Path

import config


class DatasetMissing(Exception):
    """Raised when the chosen dataset folder or files are not present."""


@dataclass(frozen=True)
class Dataset:
    name: str
    label: str
    period_start: str
    period_end: str
    log_rows: list[dict]   # each dict: row_id (int) plus the raw columns as strings
    rate_rows: list[dict]  # raw columns as strings


def _read_csv(path: Path) -> list[dict]:
    if not path.exists():
        raise DatasetMissing(f"Missing file: {path.name} in {path.parent.name}/")
    with path.open(newline="", encoding="utf-8-sig") as f:
        return [dict(r) for r in csv.DictReader(f)]


def load_dataset(name: str | None = None) -> Dataset:
    name = name or config.DATASET
    folder = config.dataset_dir(name)
    if not folder.exists():
        raise DatasetMissing(f"Dataset folder not found: data/{name}/")
    meta = json.loads((folder / "dataset.json").read_text(encoding="utf-8"))
    log = _read_csv(folder / "job_log.csv")
    for i, row in enumerate(log, start=1):
        row["row_id"] = i  # generated id; not part of the exported data
    rates = _read_csv(folder / "rate_card.csv")
    return Dataset(
        name=meta["name"],
        label=meta["label"],
        period_start=meta["period_start"],
        period_end=meta["period_end"],
        log_rows=log,
        rate_rows=rates,
    )
