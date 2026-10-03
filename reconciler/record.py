"""Record Claude's extractions for a dataset into data/<dataset>/demo_cache.json.

    python -m reconciler.record --dataset synthetic

Needs ANTHROPIC_API_KEY (environment or a local .env). Makes one API call per row.
Rows that fail are not cached; they show as held when the cache is replayed.
"""
import argparse
import os
import sys

import config
from reconciler.cache import save_cache
from reconciler.extractor import run_live
from reconciler.loader import load_dataset


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default=config.DATASET)
    args = ap.parse_args()
    config.load_dotenv()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set (environment or .env). Nothing recorded.", file=sys.stderr)
        return 1
    ds = load_dataset(args.dataset)
    print(f"Recording {len(ds.log_rows)} rows from '{ds.name}' with model {config.MODEL} ...")
    results = run_live(ds.log_rows, ds.period_start, ds.period_end)
    ok = sum(1 for e, _ in results.values() if e is not None)
    for rid, (e, err) in sorted(results.items()):
        if e is None:
            print(f"  row {rid}: FAILED ({err})")
    save_cache(ds.name, ds.log_rows, ds.period_start, ds.period_end, results, config.MODEL)
    print(f"Cached {ok}/{len(results)} rows to data/{ds.name}/demo_cache.json")
    return 0 if ok == len(results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
