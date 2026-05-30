"""Load chamber.json (521 orgs) into entities + locations + categories + contacts + social.

Idempotent: upserts entities on member_id; re-runnable. Run AFTER applying
supabase/migrations/0001_init.sql.

    python loaders/load_chamber.py
"""
import json
import os
from _common import connect, normalize_address, SEED_DIR

MEMBERSHIP = {"Standard", "Gold", "Platinum", "Pro"}


def membership(val):
    return val if val in MEMBERSHIP else "Unknown"


def upsert_location(cur, org):
    addr = (org.get("address") or "").strip()
    if not addr:
        return None
    norm = normalize_address(addr)
    cur.execute(
        """
        insert into locations (address_raw, address_norm, city, state, zip)
        values (%s, %s, %s, %s, %s)
        on conflict (address_norm) do update set address_raw = excluded.address_raw
        returning id
        """,
        (addr, norm, org.get("city"), org.get("state"), org.get("zip")),
    )
    return cur.fetchone()[0]


def upsert_entity(cur, org):
    cur.execute(
        """
        insert into entities (name, member_id, description, summary, website, phone,
                              logo_url, membership_level, is_batavia_local, source,
                              verification_status, updated_at)
        values (%s,%s,%s,%s,%s,%s,%s,%s,%s,'chamber','scraped', now())
        on conflict (member_id) do update set
            name=excluded.name, description=excluded.description, summary=excluded.summary,
            website=excluded.website, phone=excluded.phone, logo_url=excluded.logo_url,
            membership_level=excluded.membership_level, is_batavia_local=excluded.is_batavia_local,
            updated_at=now()
        returning id
        """,
        (
            org.get("name"), str(org.get("memberId")) if org.get("memberId") else None,
            org.get("description"), org.get("summary"), org.get("website"), org.get("phone"),
            org.get("logoUrl"), membership(org.get("membershipLevel")),
            bool(org.get("isBataviaLocal")),
        ),
    )
    return cur.fetchone()[0]


def link_categories(cur, entity_id, cats):
    for name in cats or []:
        cur.execute("insert into categories (name) values (%s) on conflict (name) do nothing", (name,))
        cur.execute("select id from categories where name=%s", (name,))
        cat_id = cur.fetchone()[0]
        cur.execute(
            "insert into entity_categories (entity_id, category_id) values (%s,%s) on conflict do nothing",
            (entity_id, cat_id),
        )


def load_contacts(cur, entity_id, contacts):
    cur.execute("delete from entity_contacts where entity_id=%s", (entity_id,))
    for c in contacts or []:
        cur.execute(
            "insert into entity_contacts (entity_id, name, title, phone, email) values (%s,%s,%s,%s,%s)",
            (entity_id, c.get("name"), c.get("title"), c.get("phone"), c.get("email")),
        )


def load_social(cur, entity_id, social):
    for platform, url in (social or {}).items():
        if not url:
            continue
        cur.execute(
            """insert into entity_social (entity_id, platform, url) values (%s,%s,%s)
               on conflict (entity_id, platform) do update set url=excluded.url""",
            (entity_id, platform, url),
        )


def main():
    path = os.path.join(SEED_DIR, "chamber.json")
    data = json.load(open(path))
    orgs = data.get("bataviaLocal", []) + data.get("regional", [])
    n = 0
    with connect() as conn, conn.cursor() as cur:
        for org in orgs:
            eid = upsert_entity(cur, org)
            loc_id = upsert_location(cur, org)
            if loc_id:
                cur.execute(
                    """insert into entity_location_links (entity_id, location_id, is_primary)
                       values (%s,%s,true) on conflict do nothing""",
                    (eid, loc_id),
                )
            link_categories(cur, eid, org.get("categories"))
            load_contacts(cur, eid, org.get("contacts"))
            load_social(cur, eid, org.get("socialMedia"))
            n += 1
        conn.commit()
    print(f"Loaded/updated {n} chamber entities.")


if __name__ == "__main__":
    main()
