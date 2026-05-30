"""Run the FULL live pipeline for one pilot: real homepage scout → Claude enrich.

Bypasses the dry-run synth path and the apply/write step, so you see one genuine
end-to-end enrichment. Writes ONLY scout_cache (ops); never entity data. Costs a
few cents in Claude tokens per run.

    python -m agents.enrich_one                 # default pilot
    python -m agents.enrich_one 18668           # by member_id
    python -m agents.enrich_one "Apothecary"    # by name
"""
import asyncio
import sys

from agents.config import MODEL_DEEP
from agents.db import connect, fetch_entity
from agents.enrich import _enrich_live
from agents.scout import _scout_live

DEFAULT = "18668"  # Water Street Studios


def resolve(arg):
    with connect() as c, c.cursor() as cur:
        return fetch_entity(cur, member_id=arg) if arg.isdigit() else fetch_entity(cur, name=arg)


async def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    entity = resolve(arg)
    if not entity:
        raise SystemExit(f"No entity matched '{arg}'.")

    print(f"\n=== FULL LIVE PILOT — {entity['name']} ({entity['membership_level']}) ===")
    print(f"has hours: {entity['has_hours']} | existing socials: {entity['socials'] or '(none)'}\n")

    print("① scouting (real homepage fetch)…")
    bundle = await _scout_live(entity)
    print(f"   {bundle.final_url} HTTP {bundle.status}, {len(bundle.homepage_text)} chars, "
          f"changed={bundle.changed}\n")

    print(f"② enriching with {MODEL_DEEP} (strict tool use)…")
    u = await _enrich_live(entity, bundle, MODEL_DEEP)

    print(f"\n▶ PROPOSED UPDATE  [conf {u.confidence:.2f}]")
    if u.is_empty:
        print("    (no fields proposed)")
    for k, v in u.fields.items():
        if k == "hours":
            print(f"    + hours ({len(v)} days):")
            for h in v:
                print(f"        day {h['day_of_week']}: {h['opens']}–{h['closes']}")
        elif k == "services":
            print(f"    + services: {', '.join(v[:6])}{' …' if len(v) > 6 else ''}")
        else:
            print(f"    + {k}: {v}")
    print(f"    provenance: {'; '.join(u.provenance)}")
    print(f"    tokens: in={u.usage.get('input')} out={u.usage.get('output')} "
          f"cache_read={u.usage.get('cache_read')} cache_write={u.usage.get('cache_write')}")
    print("\n✅ end-to-end live enrichment complete. (Nothing written to entity data —")
    print("   apply_update is still the review-gated write step.)")


if __name__ == "__main__":
    asyncio.run(main())
