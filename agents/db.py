"""DB access for agents. Reads run anywhere; WRITES are blocked in DRY_RUN.

In production, agents authenticate with the service_role secret key (RLS-bypass).
For the prototype we reuse DATABASE_URL (postgres owner) — same database, simpler
local run. The write guard is what matters: nothing hits production in dry-run.
"""
from __future__ import annotations

import os
import psycopg
from dotenv import load_dotenv

from agents.config import DRY_RUN

load_dotenv(override=True)


def connect():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL not set — fill .env.")
    return psycopg.connect(url)


def fetch_entity(cur, *, member_id=None, name=None):
    """Return a dict for one entity (with gap flags), or None."""
    if member_id is not None:
        cur.execute("select id, name, member_id, website, membership_level from entities where member_id=%s", (member_id,))
    else:
        cur.execute("select id, name, member_id, website, membership_level from entities where name ilike %s limit 1", (f"%{name}%",))
    row = cur.fetchone()
    if not row:
        return None
    eid, nm, mid, website, level = row
    cur.execute("select count(*) from entity_hours where entity_id=%s", (eid,))
    n_hours = cur.fetchone()[0]
    cur.execute("select coalesce(array_agg(platform), '{}') from entity_social where entity_id=%s", (eid,))
    socials = cur.fetchone()[0]
    return {
        "id": eid, "name": nm, "member_id": mid, "website": (website or "").strip(),
        "membership_level": level, "has_hours": n_hours > 0, "socials": list(socials),
    }


def apply_update(update) -> str:
    """Persist a ProposedUpdate. In DRY_RUN this is a no-op that reports intent."""
    if DRY_RUN:
        return "skipped (dry-run)"
    # Phase 0b real path (guarded until we flip DRY_RUN off):
    #   - insert entity_hours rows
    #   - upsert entity_social
    #   - insert entity_news / entity_events
    #   - write entity_changelog + entity_freshness.last_deep_enriched_at
    raise NotImplementedError("Live writes land here once DRY_RUN is off and reviewed.")
