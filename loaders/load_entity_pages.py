"""Load Tier-3 bespoke page specs from data/seed/entity_pages/*.json.

Each file is one versioned page spec (see 0014_entity_pages.sql for the
layout_json shape). Idempotent: upserts on the (entity_id, version) natural
key, so re-running after editing a spec updates the row in place. Bumping
"version" in the file creates a new row instead — the site renders the
highest published version.

Hero promotion: a published spec whose first-class hero block has an image
also becomes the entity-wide hero (entities.hero → entity.html, every
landing tier, and the directory grid) — automatically when the entity has
no hero yet, or forced with "promote_hero": true in the spec. kind stays
"community" (these are real on-location photos) so grid ranking is
unaffected; "hero_source" overrides the provenance note.

    python loaders/load_entity_pages.py
"""
import glob
import json
import os
from psycopg.types.json import Jsonb
from _common import connect, SEED_DIR

PAGES_DIR = os.path.join(SEED_DIR, "entity_pages")


def promote_hero(cur, spec):
    """Promote the page's hero image to entities.hero (see module docstring)."""
    blocks = (spec.get("layout_json") or {}).get("blocks") or []
    hero = next((b for b in blocks if b.get("type") == "hero" and b.get("image")), None)
    if not hero:
        return
    cur.execute("select hero->>'url' from entities where id=%s", (spec["entity_id"],))
    row = cur.fetchone()
    if row is None:
        return
    if row[0] and not spec.get("promote_hero", False):
        return  # entity already has a hero; overwrite only on explicit flag
    hero_json = {"url": hero["image"], "kind": "community",
                 "source": spec.get("hero_source", "bespoke page hero (business site photo)")}
    cur.execute("update entities set hero=%s, updated_at=now() where id=%s",
                (Jsonb(hero_json), spec["entity_id"]))
    print(f"   ↳ hero promoted → {hero['image'].rsplit('/', 1)[-1]}")


def main():
    files = sorted(glob.glob(os.path.join(PAGES_DIR, "*.json")))
    if not files:
        raise SystemExit(f"No .json files found in {PAGES_DIR}")
    with connect() as conn, conn.cursor() as cur:
        for path in files:
            spec = json.load(open(path))
            cur.execute(
                """
                insert into entity_pages (entity_id, tier, theme_key, layout_json, published, version, updated_at)
                values (%s, %s, %s, %s, %s, %s, now())
                on conflict (entity_id, version) do update set
                  tier = excluded.tier,
                  theme_key = excluded.theme_key,
                  layout_json = excluded.layout_json,
                  published = excluded.published,
                  updated_at = now()
                """,
                (spec["entity_id"], spec.get("tier", 3), spec.get("theme_key", "bespoke"),
                 Jsonb(spec["layout_json"]), spec.get("published", False), spec.get("version", 1)),
            )
            print(f"✅ upserted {os.path.basename(path)} "
                  f"(v{spec.get('version', 1)}, published={spec.get('published', False)})")
            if spec.get("published", False):
                promote_hero(cur, spec)
        conn.commit()
    print("Done.")


if __name__ == "__main__":
    main()
