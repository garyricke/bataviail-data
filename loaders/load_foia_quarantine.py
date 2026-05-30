"""Load foia_inspections.csv (5,455 rows) into the foia_records quarantine table.

Raw rows only — NOTHING is promoted to entities here. Classification + promotion
happen in Phase 0b. Idempotent: truncates and reloads the quarantine each run.

    python loaders/load_foia_quarantine.py
"""
import csv
import os
from _common import connect, normalize_address, SEED_DIR


def main():
    path = os.path.join(SEED_DIR, "foia_inspections.csv")
    rows = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            addr = (r.get("Address") or "").strip()
            rows.append((r.get("PBO Assigned To"), addr, normalize_address(addr)))

    with connect() as conn, conn.cursor() as cur:
        cur.execute("truncate foia_records")
        cur.executemany(
            "insert into foia_records (pbo_assigned_to, address_raw, address_norm) values (%s,%s,%s)",
            rows,
        )
        conn.commit()
        cur.execute("select count(*), count(distinct address_norm) from foia_records")
        total, distinct = cur.fetchone()
    print(f"Quarantined {total} FOIA rows ({distinct} distinct normalized addresses).")


if __name__ == "__main__":
    main()
