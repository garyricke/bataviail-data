"""Confirm we can reach the Supabase Postgres via DATABASE_URL. Prints NO secrets.

    python loaders/verify_connection.py
"""
from _common import connect


def main():
    with connect() as conn, conn.cursor() as cur:
        cur.execute("select version(), current_database(), current_user, inet_server_addr()")
        version, db, user, server_ip = cur.fetchone()
        cur.execute("select count(*) from information_schema.tables where table_schema='public'")
        public_tables = cur.fetchone()[0]
    print("✅ Connected.")
    print(f"   postgres : {version.split(' on ')[0]}")
    print(f"   database : {db}")
    print(f"   role     : {user}")
    print(f"   server   : {server_ip}")
    print(f"   public tables present: {public_tables}  (expect 0 before migration)")


if __name__ == "__main__":
    main()
