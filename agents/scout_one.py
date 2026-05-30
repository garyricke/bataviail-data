"""Run a single LIVE scout against one pilot — a real homepage fetch.

This bypasses the dry-run synth path and the (still-stubbed) enrich/apply steps,
so you can see one genuine end-to-end scout. It writes ONLY to scout_cache (an
ops cache), never to entity data.

    python -m agents.scout_one                 # default pilot
    python -m agents.scout_one 18668           # by member_id
    python -m agents.scout_one "Water Street"  # by name
"""
import asyncio
import sys

from agents.db import connect, fetch_entity
from agents.scout import _scout_live

DEFAULT = "18668"  # Water Street Studios


def resolve(arg):
    with connect() as c, c.cursor() as cur:
        if arg.isdigit():
            return fetch_entity(cur, member_id=arg)
        return fetch_entity(cur, name=arg)


async def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    entity = resolve(arg)
    if not entity:
        raise SystemExit(f"No entity matched '{arg}'.")

    print(f"\n=== LIVE SCOUT — {entity['name']} ({entity['membership_level']}) ===")
    print(f"website on record : {entity['website'] or '(none)'}")
    print(f"existing socials  : {entity['socials'] or '(none)'}")
    print(f"has hours         : {entity['has_hours']}\n")

    try:
        b = await _scout_live(entity)
    except Exception as e:
        raise SystemExit(f"❌ live fetch failed: {type(e).__name__}: {e}")

    print(f"fetched           : {b.final_url}  (HTTP {b.status})")
    print(f"changed vs cache  : {b.changed}")
    print(f"page title        : {b.title or '(none)'}")
    print(f"homepage text     : {len(b.homepage_text)} chars extracted")
    print(f"  preview         : {b.homepage_text[:200]!r}")
    print(f"NEW socials found : {b.discovered_social or '(none new)'}")
    print(f"contacts found    : {b.discovered_contacts or '(none)'}")
    print(f"search snippets   : {len(b.search_snippets)} "
          f"({'Brave on' if b.search_snippets else 'no BRAVE_API_KEY — search skipped'})")
    for s in b.search_snippets:
        print(f"    • {s[:120]}")
    print("\n✅ live scout complete. Raw body cached in scout_cache (ops only).")
    print("   Next: feed b.homepage_text to the LLM enrich step to structure hours.")


if __name__ == "__main__":
    asyncio.run(main())
