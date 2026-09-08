"""Runtime configuration and constants shared by Fantasy Command Center."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
CACHE_DIR = Path(os.getenv("CACHE_DIR", str(BASE / "data")))
CACHE_DIR.mkdir(parents=True, exist_ok=True)
REDIS_URL = (os.getenv("REDIS_URL") or os.getenv("KEY_VALUE_URL") or "").strip()
SEASON = int(os.getenv("NFL_SEASON", str(datetime.now(timezone.utc).year - (datetime.now(timezone.utc).month < 3))))
PRIOR_SEASON = SEASON - 1
TOP_N = 25
HISTORY_YEARS = 5
ALL_POSITIONS = ("QB", "RB", "WR", "TE", "K", "DST")
DRAFT_POSITIONS = ("QB", "RB", "WR", "TE")
