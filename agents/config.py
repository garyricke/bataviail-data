"""Agent swarm configuration. Dry-run by default until API keys are present."""
from __future__ import annotations

import os
from dotenv import load_dotenv

load_dotenv()

# ── Mode ──────────────────────────────────────────────────────────────────────
# DRY_RUN: no network, no LLM calls, no DB writes. Enrichment is synthesized
# deterministically so the pipeline shape is visible without spending tokens.
# SAFE DEFAULT: dry-run is ON unless you explicitly export DRY_RUN=0. (We do NOT
# infer from ANTHROPIC_API_KEY — it's often exported globally and would silently
# flip the prototype to live.)
DRY_RUN = os.environ.get("DRY_RUN", "1") != "0"

# ── Models (Path B): deep enrichment vs cheap routine refresh ─────────────────
MODEL_DEEP = "claude-sonnet-4-6"            # first-time onboarding, suspected drift
MODEL_CHEAP = "claude-haiku-4-5-20251001"  # routine refresh, prompt-cached

# ── Phase 0b pilots ───────────────────────────────────────────────────────────
# 4 are chamber members (matched by member_id); Chuck's is a known pro org that
# is NOT in the chamber data → exercises the "needs manual onboarding" branch.
PILOT_MEMBER_IDS = ["20744", "18746", "20831", "18668"]
PILOT_MISSING = ["Chuck's Cheeseburgers"]

# ── Promotion / classification thresholds ─────────────────────────────────────
# A FOIA candidate auto-promotes when classified public_facing AND it either
# exact-matches a chamber address or an independent website was found.
PROMOTE_MIN_CONFIDENCE = 0.70

# ── Freshness cadence (days) by membership tier ───────────────────────────────
CADENCE_DAYS = {"Pro": 0.25, "Platinum": 1, "Gold": 2.3, "Standard": 7, "Unknown": 14}
