"""End-to-end Data API security check, from a real PostgREST client.

Proves three things against the live REST endpoint:
  1. Publishable key CAN read entities_summary        (frontend path works)
  2. Publishable key is BLOCKED from foia_records      (quarantine RLS holds)
  3. Secret key CAN read foia_records                  (agent path works)

Prints NO secret values. Exits non-zero on any security failure.

    python loaders/verify_keys.py
"""
import json
import os
import urllib.error
import urllib.request
from dotenv import load_dotenv

load_dotenv(override=True)

BASE = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1"
PUB = os.environ["SUPABASE_ANON_KEY"]
SEC = os.environ["SUPABASE_SERVICE_ROLE_KEY"]


def get(path, key, count=False):
    """Return (status, rows, total). total parsed from Content-Range if count=True."""
    req = urllib.request.Request(BASE + path)
    req.add_header("apikey", key)
    req.add_header("Authorization", "Bearer " + key)
    if count:
        req.add_header("Prefer", "count=exact")
    try:
        with urllib.request.urlopen(req) as r:
            body = json.loads(r.read() or b"[]")
            total = None
            cr = r.headers.get("Content-Range")  # e.g. "0-0/5455"
            if cr and "/" in cr:
                total = cr.split("/")[-1]
            return r.status, body, total
    except urllib.error.HTTPError as e:
        return e.code, (e.read().decode()[:160]), None


def main():
    fails = []

    # 1. Publishable reads the public view
    st, rows, _ = get("/entities_summary?select=name&limit=3", PUB)
    ok1 = st == 200 and isinstance(rows, list) and len(rows) > 0
    print(f"1. publishable → entities_summary : HTTP {st}, {len(rows) if isinstance(rows,list) else '?'} rows  {'✅' if ok1 else '❌'}")
    if ok1:
        print(f"     sample: {[r['name'] for r in rows]}")
    else:
        fails.append("publishable cannot read entities_summary (frontend would break)")

    # 2. Publishable BLOCKED from quarantine — must NOT return data rows
    st, rows, _ = get("/foia_records?select=id&limit=1", PUB)
    leaked = st == 200 and isinstance(rows, list) and len(rows) > 0
    print(f"2. publishable → foia_records     : HTTP {st}  {'❌ LEAK' if leaked else '✅ blocked'}")
    if leaked:
        fails.append("QUARANTINE LEAK: publishable key returned foia_records rows")

    # 3. Secret key CAN read quarantine
    st, rows, total = get("/foia_records?select=id&limit=1", SEC, count=True)
    ok3 = st in (200, 206) and isinstance(rows, list)  # 206 = PostgREST ranged/limited response
    print(f"3. secret → foia_records          : HTTP {st}, total={total}  {'✅' if ok3 else '❌'}")
    if not ok3:
        fails.append("secret key cannot read foia_records (agent path would break)")

    print("─" * 50)
    if fails:
        print("❌ KEY VERIFICATION FAILED:")
        for f in fails:
            print(f"   - {f}")
        raise SystemExit(1)
    print("✅ KEYS VERIFIED — frontend reads, quarantine blocked, agent path open.")


if __name__ == "__main__":
    main()
