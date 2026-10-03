from pathlib import Path

import pytest

import config
from reconciler.loader import DatasetMissing, load_dataset


def test_synthetic_loads_with_expected_counts():
    ds = load_dataset("synthetic")
    assert ds.name == "synthetic"
    assert len(ds.log_rows) == 15
    assert len(ds.rate_rows) == 9
    assert [r["row_id"] for r in ds.log_rows] == list(range(1, 16))


def test_raw_values_are_untouched():
    ds = load_dataset("synthetic")
    # mess is kept: mixed date formats, odd spellings, blanks
    assert ds.log_rows[1]["Date"] == "2026-11-03"
    assert ds.log_rows[3]["Date"] == "03-Nov"
    assert ds.log_rows[4]["Service"] == "Push back"
    assert ds.log_rows[4]["End"] == ""


def test_unknown_dataset_raises():
    with pytest.raises(DatasetMissing):
        load_dataset("does_not_exist")


def test_default_dataset_is_synthetic(monkeypatch):
    # a deployed copy must never default to sample data
    assert Path(config.__file__).read_text().count('"DATASET", "synthetic"') == 1


def test_gitignore_excludes_sample_and_secrets():
    text = (config.ROOT / ".gitignore").read_text()
    for line in (".env", "data/sample/", "tests_private/", "*.pdf"):
        assert line in text.splitlines()
