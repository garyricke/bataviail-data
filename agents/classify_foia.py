"""Phase 0b: classify the FOIA quarantine to surface ~175 public-facing businesses.

Reads distinct quarantine addresses and assigns a classification + confidence.
DRY_RUN uses a cheap heuristic (chamber-address overlap = strong public-facing
signal); the live path would send ambiguous rows to an LLM + web lookup. Nothing
is promoted to entity_candidates in dry-run — it reports what it WOULD promote.

    python -m agents.classify_foia
"""
from __future__ import annotations

from agents.config import DRY_RUN, PROMOTE_MIN_CONFIDENCE
from agents.db import connect


def load_distinct_addresses(cur):
    """One row per normalized address, flagged for chamber overlap."""
    cur.execute("""
        select f.address_norm,
               min(f.address_raw)     as address_raw,
               min(f.pbo_assigned_to) as pbo,
               bool_or(l.id is not null) as chamber_overlap
        from foia_records f
        left join locations l on l.address_norm = f.address_norm
        where f.address_norm is not null
        group by f.address_norm
    """)
    return cur.fetchall()


def classify(address_raw, pbo, chamber_overlap):
    """Return (classification, confidence). Heuristic in dry-run."""
    if not DRY_RUN:  # pragma: no cover - live path
        raise NotImplementedError("LLM + web classifier lands here when DRY_RUN is off.")
    if chamber_overlap:
        # Address already maps to a known chamber business → public-facing.
        return "public_facing", 0.80
    # Without a chamber match we can't tell from address alone → defer to LLM.
    return "unknown", 0.30


def run():
    mode = "DRY-RUN (heuristic, no promotions)" if DRY_RUN else "LIVE"
    print(f"\n=== Phase 0b FOIA classification — {mode} ===\n")
    with connect() as conn, conn.cursor() as cur:
        rows = load_distinct_addresses(cur)

    counts = {"public_facing": 0, "unknown": 0, "non_public": 0}
    would_promote = []
    for address_norm, address_raw, pbo, overlap in rows:
        cls, conf = classify(address_raw, pbo, overlap)
        counts[cls] += 1
        if cls == "public_facing" and conf >= PROMOTE_MIN_CONFIDENCE:
            would_promote.append((address_raw, conf))

    print(f"distinct quarantine addresses : {len(rows)}")
    for k, v in counts.items():
        print(f"  {k:<14} {v}")
    print(f"\nwould promote to entity_candidates (conf ≥ {PROMOTE_MIN_CONFIDENCE}): {len(would_promote)}")
    for addr, conf in would_promote[:8]:
        print(f"    • [{conf:.2f}] {addr}")
    if len(would_promote) > 8:
        print(f"    … +{len(would_promote) - 8} more")

    remaining = counts["unknown"]
    print("\n─" * 1 + "─" * 57)
    print(f"auto-classified via chamber overlap: {len(would_promote)} | "
          f"need LLM+web pass: {remaining}")
    if DRY_RUN:
        print("DRY-RUN: the 'unknown' rows are where the real LLM classifier earns its keep.")


if __name__ == "__main__":
    run()
