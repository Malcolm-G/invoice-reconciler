"""The only module that talks to Claude. One call per row; any failure holds that row.

Uses the Anthropic SDK's structured-output helper (messages.parse with a Pydantic
model). The result is validated again here: a refusal, a cut-off reply, invalid
output or an API error all become (None, reason), which tiering turns into a held row.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed

import anthropic
from pydantic import ValidationError

import config
from reconciler.models import RowExtraction
from reconciler.prompts import SYSTEM_PROMPT, user_message

Extraction = tuple[RowExtraction | None, str]


def extract_row(client, raw: dict, period_start: str, period_end: str,
                model: str | None = None) -> Extraction:
    try:
        response = client.messages.parse(
            model=model or config.MODEL,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message(raw, period_start, period_end)}],
            output_format=RowExtraction,
        )
    except ValidationError:
        return None, "Claude's answer for this row wasn't usable (wrong format)."
    except anthropic.RateLimitError:
        return None, "Claude couldn't read this row (too many requests)."
    except anthropic.APIConnectionError:
        return None, "Claude couldn't read this row (no connection)."
    except anthropic.APIStatusError as e:
        return None, f"Claude couldn't read this row (error {e.status_code})."
    except Exception as e:  # fail safe: nothing may escape the row it happened on
        return None, f"Claude couldn't read this row (unexpected {type(e).__name__})."

    ext = getattr(response, "parsed_output", None)
    if ext is None:
        reason = getattr(response, "stop_reason", None)
        return None, f"Claude's answer for this row wasn't usable (stop reason: {reason})."
    try:
        ext = RowExtraction.model_validate(ext.model_dump())  # validate again, independent of the SDK
    except (ValidationError, AttributeError):
        return None, "Claude's answer for this row wasn't usable (wrong format)."
    if ext.row_id != raw["row_id"]:
        return None, "Claude's answer was for a different row."
    return ext, ""


def run_live(rows: list[dict], period_start: str, period_end: str,
             model: str | None = None, client=None, workers: int = 4,
             on_progress=None) -> dict[int, Extraction]:
    """Call Claude once per row (a few at a time). Needs ANTHROPIC_API_KEY in the environment.
    on_progress(done, total) is called as rows finish."""
    client = client or anthropic.Anthropic()  # reads ANTHROPIC_API_KEY; never hard-coded
    results: dict[int, Extraction] = {}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(extract_row, client, raw, period_start, period_end, model): raw["row_id"]
                   for raw in rows}
        for done, fut in enumerate(as_completed(futures), start=1):
            results[futures[fut]] = fut.result()
            if on_progress:
                on_progress(done, len(rows))
    return {raw["row_id"]: results[raw["row_id"]] for raw in rows}  # original row order
