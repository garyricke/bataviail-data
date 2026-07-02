"""Load Tier-3 bespoke page specs from data/seed/entity_pages/*.json.

Each file is one versioned page spec (see 0014_entity_pages.sql for the
layout_json shape). Idempotent: upserts on the (entity_id, version) natural
key, so re-running after editing a spec updates the row in place. Bumping
"version" in the file creates a new row instead — the site renders the
highest published version.

    python loaders/load_entity_pages.py
"""
import glob
import json
import os
from psycopg.types.json import Jsonb
from _common import connect, SEED_DIR

PAGES_DIR = os.path.join(SEED_DIR, "entity_pages")


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
        conn.commit()
    print("Done.")


if __name__ == "__main__":
    main()
