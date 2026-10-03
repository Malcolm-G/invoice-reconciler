# Data

## data/sample/ (local only, gitignored)
Sample data supplied by the repo author for demonstration. Permission to publish not confirmed in writing. Treat as sample data, not verified or live client data.

This folder is excluded from git and is never committed. Anything derived from it (its demo cache, its tests) is excluded too.

## data/synthetic/
Invented flights, dates and rates, with the same kinds of mess as the sample. Safe to publish. See `CASES.md` for what each row exercises.

## data/mappings/
Visible lookup tables used by plain code: aircraft code to category, leg type spelling, service spelling. A `status` of `assumed` in `aircraft.csv` means the mapping has not been verified.
