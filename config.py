"""Single place for settings. Everything comes from env vars with safe defaults.

DATASET is the one switch between datasets. It defaults to "synthetic" so a
deployed copy never touches sample data.
"""
import os
from pathlib import Path

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"

DATASET = os.environ.get("DATASET", "synthetic")
MODEL = os.environ.get("MODEL", "claude-haiku-4-5")  # small, cheap default; override with MODEL
PROMPT_VERSION = "v4"  # bump when the prompt or schema changes; cached results from other versions are ignored


def dataset_dir(dataset: str = DATASET) -> Path:
    return DATA_DIR / dataset


def load_dotenv() -> None:
    """Read ANTHROPIC_API_KEY (and other vars) from a local .env if present. .env is gitignored."""
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
