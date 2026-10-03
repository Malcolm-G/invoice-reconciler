"""Who may trigger live Claude calls. Fails closed: with a key present, live use needs either the
passcode, or ALLOW_OPEN_LIVE=1 (set only in a local .env). No Streamlit, no Claude here."""
import hmac
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Access:
    allowed: bool
    reason: str          # shown to the user when not allowed
    needs_passcode: bool


def live_access(entered_passcode: str = "", env: dict | None = None) -> Access:
    env = os.environ if env is None else env
    if not env.get("ANTHROPIC_API_KEY"):
        return Access(False, "Uploading your own file isn't switched on for this copy of the app.", False)
    if env.get("ALLOW_OPEN_LIVE") == "1":
        return Access(True, "", False)
    expected = env.get("APP_PASSCODE", "")
    if not expected:
        return Access(False, "Uploading your own file isn't switched on for this copy of the app.", False)
    if not entered_passcode:
        return Access(False, "Enter the passcode (it's on the CV) to upload your own file.", True)
    if hmac.compare_digest(entered_passcode.encode(), expected.encode()):
        return Access(True, "", True)
    return Access(False, "That passcode isn't right.", True)


def session_budget_left(used_rows: int, wanted_rows: int, limit: int) -> bool:
    return used_rows + wanted_rows <= limit
