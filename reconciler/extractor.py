"""The only module that talks to Claude. One call per row; any failure holds that row.

Uses the Anthropic SDK's structured-output helper (messages.parse with a Pydantic
model). The result is validated again here: a refusal, a cut-off reply, invalid
output or an API error all become (None, reason), which tiering turns into a held row.
"""
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
        return None, "Extraction failed validation."
    except anthropic.RateLimitError:
        return None, "Extraction failed: rate limited."
    except anthropic.APIConnectionError:
        return None, "Extraction failed: could not reach the API."
    except anthropic.APIStatusError as e:
        return None, f"Extraction failed: API error {e.status_code}."

    ext = getattr(response, "parsed_output", None)
    if ext is None:
        reason = getattr(response, "stop_reason", None)
        return None, f"Extraction failed: no valid output (stop reason: {reason})."
    try:
        ext = RowExtraction.model_validate(ext.model_dump())  # validate again, independent of the SDK
    except (ValidationError, AttributeError):
        return None, "Extraction failed validation."
    if ext.row_id != raw["row_id"]:
        return None, "Extraction failed: row_id does not match the input row."
    return ext, ""


def run_live(rows: list[dict], period_start: str, period_end: str,
             model: str | None = None, client=None) -> dict[int, Extraction]:
    """Call Claude once per row. Needs ANTHROPIC_API_KEY in the environment."""
    client = client or anthropic.Anthropic()  # reads ANTHROPIC_API_KEY; never hard-coded
    return {raw["row_id"]: extract_row(client, raw, period_start, period_end, model) for raw in rows}
