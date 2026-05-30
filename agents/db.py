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
    """Persist a ProposedUpdate DIRECTLY to live entity tables (data-build phase:
    no review gate). Every change set is recorded in entity_changelog for audit
    and reversibility. In DRY_RUN this is a no-op that reports intent.

    Idempotent: hours and services are agent-owned and replaced wholesale;
    social/contacts upsert; summary overwrites (old value preserved in changelog).
    """
    from psycopg.types.json import Json

    if DRY_RUN:
        return "skipped (dry-run)"
    fields = update.fields
    if not fields:
        return "no changes"

    eid = update.entity_id
    changes: dict = {}
    with connect() as conn, conn.cursor() as cur:
        if "summary" in fields:
            cur.execute("select summary from entities where id=%s", (eid,))
            old = cur.fetchone()[0]
            cur.execute("update entities set summary=%s, updated_at=now() where id=%s", (fields["summary"], eid))
            changes["summary"] = {"old": old, "new": fields["summary"]}

        if "hours" in fields:  # agent owns hours → replace
            cur.execute("delete from entity_hours where entity_id=%s", (eid,))
            for h in fields["hours"]:
                cur.execute(
                    "insert into entity_hours (entity_id, day_of_week, opens, closes) values (%s,%s,%s,%s)",
                    (eid, h["day_of_week"], h.get("opens") or None, h.get("closes") or None),
                )
            changes["hours"] = {"new_count": len(fields["hours"])}

        if "services" in fields:  # replace
            cur.execute("delete from entity_services where entity_id=%s", (eid,))
            for s in fields["services"]:
                cur.execute(
                    "insert into entity_services (entity_id, name) values (%s,%s) on conflict do nothing",
                    (eid, s),
                )
            changes["services"] = {"new_count": len(fields["services"])}

        if "social" in fields:  # upsert
            for plat, url in fields["social"].items():
                cur.execute(
                    """insert into entity_social (entity_id, platform, url) values (%s,%s,%s)
                       on conflict (entity_id, platform) do update set url=excluded.url""",
                    (eid, plat, url),
                )
            changes["social"] = list(fields["social"].keys())

        if "contacts" in fields:
            c = fields["contacts"]
            email, phone = c.get("email"), c.get("phone")
            if email:  # add a discovered contact only if that email isn't already on file
                cur.execute("select 1 from entity_contacts where entity_id=%s and lower(email)=lower(%s)", (eid, email))
                if not cur.fetchone():
                    cur.execute(
                        "insert into entity_contacts (entity_id, name, title, email, phone) values (%s,'Website','auto-discovered',%s,%s)",
                        (eid, email, phone),
                    )
                    changes["contact"] = {"email": email, "phone": phone}
            if phone:  # backfill the entity phone only when missing
                cur.execute("update entities set phone=%s where id=%s and (phone is null or phone='')", (phone, eid))

        if "events" in fields:
            import re as _re
            n_ev = 0
            for ev in fields["events"]:
                title = (ev.get("title") or "").strip()
                if not title:
                    continue
                date = (ev.get("date") or "").strip()
                time = (ev.get("time") or "").strip()
                starts_at = None
                if _re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
                    t = time if _re.fullmatch(r"\d{2}:\d{2}", time) else "00:00"
                    starts_at = f"{date}T{t}:00"
                dedup = _re.sub(r"\s+", " ", title.lower()).strip() + "|" + date
                cur.execute(
                    """insert into entity_events
                         (entity_id, title, description, starts_at, all_day, location, url, price, source, dedup_key)
                       values (%s,%s,%s,%s,%s,%s,%s,%s,'entity_site',%s)
                       on conflict (entity_id, dedup_key) do update set
                         title=excluded.title, description=excluded.description,
                         starts_at=excluded.starts_at, all_day=excluded.all_day,
                         location=excluded.location, url=excluded.url, price=excluded.price,
                         found_at=now()""",
                    (eid, title, ev.get("description") or None, starts_at, not bool(time),
                     ev.get("location") or None, ev.get("url") or None, ev.get("price") or None, dedup),
                )
                n_ev += 1
            if n_ev:
                changes["events"] = {"new_count": n_ev}

        # Audit + freshness + verification status
        cur.execute(
            """insert into entity_changelog (entity_id, source, model, confidence, changes)
               values (%s,'agent_enrich',%s,%s,%s)""",
            (eid, update.model, update.confidence, Json(changes)),
        )
        cur.execute(
            """insert into entity_freshness (entity_id, last_checked_at, last_deep_enriched_at)
               values (%s, now(), now())
               on conflict (entity_id) do update set last_checked_at=now(), last_deep_enriched_at=now()""",
            (eid,),
        )
        cur.execute(
            "update entities set verification_status='scraped', last_verified_by=%s where id=%s",
            (update.model, eid),
        )
        conn.commit()

    return "applied: " + (", ".join(changes) if changes else "no-op")
