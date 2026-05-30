"""Shared helpers for loaders: DB connection + address normalization."""
from __future__ import annotations

import os
import re
import psycopg
from dotenv import load_dotenv

load_dotenv()

SEED_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "seed")


def connect():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL not set — copy .env.example to .env and fill it in.")
    return psycopg.connect(url)


_SUFFIX = {
    "street": "st", "st": "st", "avenue": "ave", "ave": "ave", "road": "rd",
    "rd": "rd", "drive": "dr", "dr": "dr", "boulevard": "blvd", "blvd": "blvd",
    "lane": "ln", "ln": "ln", "court": "ct", "ct": "ct", "place": "pl",
    "pl": "pl", "circle": "cir", "cir": "cir", "highway": "hwy", "hwy": "hwy",
}


def normalize_address(addr: str | None) -> str | None:
    """Lowercase, strip punctuation, canonicalize street suffixes for dedupe/matching."""
    if not addr:
        return None
    s = addr.lower().strip()
    s = re.sub(r"[.,#]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    parts = [_SUFFIX.get(w, w) for w in s.split(" ")]
    return " ".join(parts) or None
