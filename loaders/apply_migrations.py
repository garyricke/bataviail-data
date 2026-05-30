"""Apply every .sql file in supabase/migrations/ in filename order.

Migrations are written to be idempotent (IF NOT EXISTS / OR REPLACE), so this is
safe to re-run. Run before the loaders.

    python loaders/apply_migrations.py
"""
import glob
import os
from _common import connect

MIG_DIR = os.path.join(os.path.dirname(__file__), "..", "supabase", "migrations")


def main():
    files = sorted(glob.glob(os.path.join(MIG_DIR, "*.sql")))
    if not files:
        raise SystemExit(f"No .sql files found in {MIG_DIR}")
    with connect() as conn:
        for path in files:
            sql = open(path).read()
            with conn.cursor() as cur:
                cur.execute(sql)
            conn.commit()
            print(f"✅ applied {os.path.basename(path)}")
    print("Done.")


if __name__ == "__main__":
    main()
