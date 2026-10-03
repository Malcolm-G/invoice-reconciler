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

## Upload your own file
Choose "Upload a file" in the sidebar. Upload a job log (`.csv` or `.xlsx`) and optionally a rate card. Claude reads each row live, then the same code-only pricing, tiering and checks produce the draft, which can be downloaded as CSV.
- Templates for both files are downloadable in the app. Date and Service columns are required; at most 50 rows per upload.
- Values are read as text, exactly as exported. Excel date and time cells become plain text; an Excel time stored as a bare fraction cannot be recovered and holds the line.
- Pick the batch week (used only to read dates that have no year).
- With no rate card uploaded, a banner says the synthetic demo prices are in use.
- Uploaded rows are sent to the Anthropic API. The app does not store them, and uploads are never written to the cache files.

## Hosted deployment and secrets
The public demo needs no secrets: it replays the cached synthetic results. To enable uploads on a hosted copy, add these in the host's secrets settings (never in the repo):
- `ANTHROPIC_API_KEY`
- `APP_PASSCODE` (live reading is refused unless the visitor enters it; with a key but no passcode it stays switched off)

Controls: the row cap per upload (`MAX_UPLOAD_ROWS`, default 50) and a per-session limit on live row reads (`MAX_LIVE_ROWS_PER_SESSION`, default 150). `ALLOW_OPEN_LIVE=1` skips the passcode and is for a local `.env` only; the "Re-record" button also needs it, so it never appears on a hosted app. The passcode is a simple gate, not a full login system, and there is no attempt throttling.

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
