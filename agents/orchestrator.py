"""Phase 0b orchestrator (prototype).

Runs the pilot enrichment pass: load pilots → scout + enrich concurrently →
report proposed writes. In DRY_RUN nothing is written; it prints what it WOULD do.

    python -m agents.orchestrator
"""
from __future__ import annotations

import asyncio

from agents.config import DRY_RUN, PILOT_MEMBER_IDS, PILOT_MISSING
from agents.db import apply_update, connect, fetch_entity
from agents.enrich import enrich
from agents.scout import scout


def load_pilots():
    """Return (found_entities, missing_names). Missing = not in chamber data."""
    found, missing = [], []
    with connect() as conn, conn.cursor() as cur:
        for mid in PILOT_MEMBER_IDS:
            e = fetch_entity(cur, member_id=mid)
            (found if e else missing).append(e or f"member_id={mid}")
        for name in PILOT_MISSING:
            e = fetch_entity(cur, name=name)
            (found if e else missing).append(e or name)
    return [e for e in found if isinstance(e, dict)], [m for m in (missing) if not isinstance(m, dict)]


async def process(entity) -> "ProposedUpdate":
    # First-time onboarding for a pilot → deep enrichment.
    bundle = await scout(entity)
    return await enrich(entity, bundle, deep=True)


async def run():
    found, missing = load_pilots()
    mode = "DRY-RUN (no writes, synthesized data)" if DRY_RUN else "LIVE"
    print(f"\n=== Phase 0b pilot enrichment — {mode} ===\n")

    # Scout + enrich all pilots concurrently (Path B: asyncio fan-out).
    updates = await asyncio.gather(*(process(e) for e in found))

    applied = 0
    for u in updates:
        print(f"▶ {u.entity_name}  [{u.model}, conf {u.confidence:.2f}]")
        if u.is_empty:
            print("    no gaps found — nothing to propose")
        for key, val in u.fields.items():
            preview = f"{len(val)} rows" if isinstance(val, list) else val
            print(f"    + {key}: {preview}")
        if u.provenance:
            print(f"    provenance: {'; '.join(u.provenance)}")
        status = apply_update(u)
        print(f"    write: {status}\n")
        applied += 0 if DRY_RUN else 1

    if missing:
        print("⚠ Not in chamber data — route to MANUAL ONBOARDING (entity_candidates):")
        for m in missing:
            print(f"    • {m}")
        print()

    print("─" * 58)
    print(f"pilots enriched: {len(found)} | proposed updates: "
          f"{sum(1 for u in updates if not u.is_empty)} | "
          f"manual-onboarding: {len(missing)} | written: {applied}")
    if DRY_RUN:
        print("DRY-RUN: set ANTHROPIC_API_KEY (+ DRY_RUN=0) to enrich for real.")


if __name__ == "__main__":
    asyncio.run(run())
