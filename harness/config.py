"""Central configuration constants."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = ROOT / "docs_noibo"
NOTES_DIR = ROOT / "notes"
LOGS_DIR = ROOT / "logs"
EVAL_DIR = ROOT / "eval"

DEFAULT_MODEL = os.getenv("HARNESS_MODEL", "claude-sonnet-5-5")
DEFAULT_MAX_TURNS = int(os.getenv("HARNESS_MAX_TURNS", "6"))
MAX_TOKENS = 16000
EFFORT = "medium"
