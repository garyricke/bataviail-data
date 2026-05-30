"""Phase 0a data-verification gate. Proves the loaded data layer is sound
BEFORE any UI is built on it. Read-only; prints a report and exits non-zero if
any hard invariant fails.

    python loaders/verify_data.py
"""
from _common import connect

EXPECT_ENTITIES = 521
EXPECT_FOIA = 5455


def main():
    problems = []
    with connect() as conn, conn.cursor() as cur:

        def scalar(q, *a):
            cur.execute(q, a)
            return cur.fetchone()[0]

        print("── ENTITIES ──────────────────────────────────────────────")
        n = scalar("select count(*) from entities")
        local = scalar("select count(*) from entities where is_batavia_local")
        regional = n - local
        print(f"  total entities        : {n}  (expect {EXPECT_ENTITIES})")
        print(f"  local / regional      : {local} / {regional}  (expect 291 / 230)")
        print(f"  unique member_id      : {scalar('select count(distinct member_id) from entities')}")
        print(f"  membership breakdown  :")
        cur.execute("select membership_level, count(*) from entities group by 1 order by 2 desc")
        for lvl, c in cur.fetchall():
            print(f"      {lvl:<10} {c}")
        if n != EXPECT_ENTITIES:
            problems.append(f"entities count {n} != {EXPECT_ENTITIES}")

        print("\n── LOCATIONS (multi-tenant) ──────────────────────────────")
        print(f"  distinct locations    : {scalar('select count(*) from locations')}")
        print(f"  entities w/ location  : {scalar('select count(distinct entity_id) from entity_location_links')}")
        cur.execute("""
            select l.address_raw, count(*) c
            from entity_location_links ell join locations l on l.id = ell.location_id
            group by l.address_raw having count(*) > 1 order by c desc limit 5
        """)
        shared = cur.fetchall()
        print(f"  shared addresses (top): " + ("none" if not shared else ""))
        for addr, c in shared:
            print(f"      {c}×  {addr}")

        print("\n── ATTRIBUTES ────────────────────────────────────────────")
        print(f"  categories (distinct) : {scalar('select count(*) from categories')}")
        print(f"  entity_categories     : {scalar('select count(*) from entity_categories')}")
        print(f"  contacts              : {scalar('select count(*) from entity_contacts')}")
        print(f"  social links          : {scalar('select count(*) from entity_social')}")
        print(f"  hours rows            : {scalar('select count(*) from entity_hours')}  (expect 0 — chamber has none)")

        print("\n── FOIA QUARANTINE ───────────────────────────────────────")
        f = scalar("select count(*) from foia_records")
        print(f"  foia_records          : {f}  (expect {EXPECT_FOIA})")
        print(f"  distinct norm address : {scalar('select count(distinct address_norm) from foia_records')}")
        print(f"  unclassified          : {scalar('select count(*) from foia_records where classification is null')}  (expect all — 0b classifies)")
        overlap = scalar("""
            select count(distinct f.address_norm) from foia_records f
            join locations l on l.address_norm = f.address_norm
        """)
        print(f"  address overlap w/ chamber locations : {overlap}")
        if f != EXPECT_FOIA:
            problems.append(f"foia count {f} != {EXPECT_FOIA}")

        print("\n── PUBLIC VIEWS ──────────────────────────────────────────")
        print(f"  entities_summary rows : {scalar('select count(*) from entities_summary')}")
        print(f"  entity_full rows      : {scalar('select count(*) from entity_full')}")
        cur.execute("select name, categories, city from entities_summary where categories <> '{}' limit 1")
        row = cur.fetchone()
        print(f"  sample summary row    : {row}")

        print("\n── SECURITY (Data API grants) ────────────────────────────")
        cur.execute("""
            select table_name from information_schema.role_table_grants
            where grantee='anon' and privilege_type='SELECT'
              and table_schema='public' order by table_name
        """)
        anon_tables = [r[0] for r in cur.fetchall()]
        print(f"  anon can SELECT       : {', '.join(anon_tables)}")
        leaked = [t for t in ('foia_records', 'entity_candidates', 'candidate_matches') if t in anon_tables]
        if leaked:
            problems.append(f"QUARANTINE LEAK: anon has SELECT on {leaked}")
        else:
            print("  quarantine tables NOT anon-readable ✅")

    print("\n" + "═" * 58)
    if problems:
        print("❌ VERIFICATION FAILED:")
        for p in problems:
            print(f"   - {p}")
        raise SystemExit(1)
    print("✅ DATA LAYER VERIFIED — safe to build on.")


if __name__ == "__main__":
    main()
