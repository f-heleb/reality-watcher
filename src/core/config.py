"""
sreality_watcher/config.py

Centralized configuration & defaults.
- Loads environment variables (supports .env via python-dotenv).
- Holds constants used across modules.
"""

from __future__ import annotations
import os
from dotenv import load_dotenv

# Load .env if present (non-fatal if missing)
load_dotenv()

# ---- Slack tokens (required for Socket Mode manager) ----
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SLACK_BOT_TOKEN: str | None = os.environ.get("SLACK_BOT_TOKEN")   # xoxb-...
SLACK_APP_TOKEN: str | None = os.environ.get("SLACK_APP_TOKEN")   # xapp-...

# ---- Intervals & paths ----
# Default polling interval (seconds). If you saw 300 earlier, this ensures 60 by default.
DEFAULT_INTERVAL_SEC: int = int(os.environ.get("DEFAULT_INTERVAL_SEC", "60"))

# JSON persistence (can be swapped later for SQLite/Redis)
# Paths are relative to project root
CONFIG_PATH: str = os.environ.get("WATCHERS_JSON", "config/watchers.json")
STATE_PATH: str = os.environ.get("SEEN_STATE_JSON", "config/seen_state.json")

# ---- HTTP/scraper defaults ----
USER_AGENT: str = os.environ.get(
    "USER_AGENT",
    "Mozilla/5.0 (compatible; SrealityWatcher/modular; +https://example.local)"
)
BASE_DOMAIN: str = os.environ.get("BASE_DOMAIN", "https://www.sreality.cz")

# ---- Helpers ----
def require_slack_tokens() -> None:
    """
    Raise a clear error if Slack tokens are missing.
    Call this early in CLI entrypoints.
    """
    missing = []
    if not SLACK_BOT_TOKEN:
        missing.append("SLACK_BOT_TOKEN")
    if not SLACK_APP_TOKEN:
        missing.append("SLACK_APP_TOKEN")
    if missing:
        raise RuntimeError(
            "Missing required environment variables: "
            + ", ".join(missing)
            + ". Set them in your environment or a .env file."
        )

def print_effective_config() -> None:
    """
    Small debug helper to log effective (non-secret) config.
    Avoids printing token values.
    """
    print(
        "[config] DEFAULT_INTERVAL_SEC =", DEFAULT_INTERVAL_SEC,
        "| CONFIG_PATH =", CONFIG_PATH,
        "| STATE_PATH =", STATE_PATH,
        "| USER_AGENT =", USER_AGENT,
        "| BASE_DOMAIN =", BASE_DOMAIN,
    )