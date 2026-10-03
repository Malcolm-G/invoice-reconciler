# Invoice Reconciler

**Status: prototype.** The pipeline runs end to end: Claude reads and flags each log row, and plain code prices, tiers and totals the result into a draft invoice. Not built yet: the exceptions queue and the approval gate.

Creates a draft invoice for human review from a messy job log and a price list. The design rule: Claude reads and flags rows; plain code does every lookup and calculation. Claude's output schema has no price or total fields.

## What exists
- Loading of a job log and rate card, kept exactly as exported.
- Claude extraction, one call per row, with structured output validated twice. Any invalid or failed result holds that row (billed 0).
- Cached demo mode: recorded Claude outputs replay with no API key and no network. The UI says so in a banner.
- Plain-code normalisation: dates (read as DD/MM), strict times, aircraft/leg/service mapping tables in `data/mappings/`.
- Exact-match rate lookup (service, aircraft category, leg). No nearest-rate fallback.
- Per-line tiers: firm, assumed, held, duplicate.
- Day-by-day draft invoice view, held items listed separately, three code-verified checks.

## What does not exist yet
Exceptions queue (questions per held line, grouped by owner) and the approval gate.

## Trust boundary
Code reads every field from the raw text itself and compares it with Claude's reading. Any disagreement holds the line. Claude can only add caution (flags); it cannot lower a hold code found, and it never sets an amount. A log note passes only if Claude says it just restates a gap and code independently sees that gap.

## Run
```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
pytest
```
`DATASET` defaults to `synthetic`. Replaying the cache needs no API key.

To record fresh Claude outputs, put `ANTHROPIC_API_KEY=...` in a local `.env` (gitignored) and run `python -m reconciler.record --dataset synthetic`. `MODEL` overrides the default model, `claude-haiku-4-5`.

## Findings on model choice
Prompt iterations: four versions, tuned on both the synthetic and the sample data, so the sample result is not an independent test.
- Synthetic set: the small model (Haiku 4.5) reproduces the expected invoice exactly.
- Sample set: Haiku 4.5 consistently flags a truncated end time more cautiously than needed, so one flat-rate line is held (the safe direction). A larger model (Sonnet 5.5) gave the expected result. Raising caution is by design; this is a model-judgement limit, not a calculation error.
- Each cache file records which model made it; the banner shows it.

## Pricing assumption
Pro-rata read as per minute; confirm with ops.

## Known limitations
- Dates are read as DD/MM.
- Aircraft shorthand marked `assumed` in `data/mappings/aircraft.csv` is not verified; lines using it say so.
- Times that could be misread (for example "10" or "7:10" with no am/pm) are treated as unreadable, never guessed.
- Model output varies between runs; the cache is what makes the demo repeatable.
- Single-week batches only. No persistence.
