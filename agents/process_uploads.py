"""Process the photo-capture queue: enhance each upload to the locked house style,
store the hero in Supabase Storage, reverse-geocode its GPS to an address, and set
it as the entity's hero. Run after shooting (or with --loop to keep watching).

    python -m agents.process_uploads            # process all pending once
    python -m agents.process_uploads --loop     # keep polling every 20s
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from dotenv import load_dotenv
from PIL import Image
from psycopg.types.json import Json

from agents.db import connect

load_dotenv(".env", override=True)
SUPA = os.environ["SUPABASE_URL"].rstrip("/")
SERVICE = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
BUCKET = "media"

# The locked "house style" — identical for every contributor's photo. This is the
# single knob that makes all uploads share one consistent aesthetic.
HOUSE_STYLE = (
    "Re-grade and retouch this casual phone snapshot into a polished, professional "
    "editorial photograph of the EXACT same real scene, as if shot by a commercial "
    "photographer. Apply this consistent house style: bright clean natural light with "
    "gentle warmth, rich yet true-to-life color, balanced exposure with recovered "
    "highlights and lifted shadows, crisp detail, pleasing gentle contrast, and tidy "
    "professional composition. Keep the real building, storefront, signage, text and "
    "layout EXACTLY as they are — do not invent, remove, move, or alter any structures, "
    "words, or logos. Stay fully photographic and realistic. No added text, borders, or watermarks."
)


def _openai():
    from openai import OpenAI
    return OpenAI()


# ── Supabase Storage ──────────────────────────────────────────────────────────
def storage_download(path: str) -> bytes:
    with urllib.request.urlopen(f"{SUPA}/storage/v1/object/public/{BUCKET}/{path}", timeout=30) as r:
        return r.read()


def storage_upload(path: str, data: bytes, content_type="image/jpeg") -> str:
    req = urllib.request.Request(
        f"{SUPA}/storage/v1/object/{BUCKET}/{path}", data=data, method="POST",
        headers={"apikey": SERVICE, "Authorization": "Bearer " + SERVICE,
                 "Content-Type": content_type, "x-upsert": "true"},
    )
    try:
        urllib.request.urlopen(req, timeout=60).read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"storage upload {e.code}: {e.read().decode()[:200]}") from None
    return f"{SUPA}/storage/v1/object/public/{BUCKET}/{path}"


# ── geocoding ─────────────────────────────────────────────────────────────────
def reverse_geocode(lat, lng):
    if lat is None or lng is None:
        return None
    url = f"https://nominatim.openstreetmap.org/reverse?format=jsonv2&lat={lat}&lon={lng}&zoom=18"
    req = urllib.request.Request(url, headers={"User-Agent": "BataviaIL-Directory/0.1 (capture)"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            a = json.loads(r.read()).get("address", {})
    except Exception:
        return None
    street = " ".join(x for x in [a.get("house_number"), a.get("road")] if x)
    return {
        "address": street or None,
        "city": a.get("city") or a.get("town") or a.get("village"),
        "state": a.get("state"),
        "zip": a.get("postcode"),
    }


def set_location(cur, eid, geo):
    if not geo or not geo.get("address"):
        return
    norm = geo["address"].lower().strip()
    cur.execute(
        """insert into locations (address_raw, address_norm, city, state, zip)
           values (%s,%s,%s,%s,%s) on conflict (address_norm) do update set city=excluded.city
           returning id""",
        (geo["address"], norm, geo.get("city"), geo.get("state"), geo.get("zip")),
    )
    loc_id = cur.fetchone()[0]
    # make it the entity's primary location (only if it has none yet)
    cur.execute("select 1 from entity_location_links where entity_id=%s", (eid,))
    if not cur.fetchone():
        cur.execute(
            "insert into entity_location_links (entity_id, location_id, is_primary) values (%s,%s,true) on conflict do nothing",
            (eid, loc_id),
        )


# ── image ─────────────────────────────────────────────────────────────────────
def enhance(client, raw: bytes) -> bytes:
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    img.thumbnail((1536, 1536))
    w, h = img.size
    size = "1536x1024" if w > h * 1.1 else ("1024x1536" if h > w * 1.1 else "1024x1024")
    buf = io.BytesIO(); img.save(buf, "PNG"); buf.seek(0)
    r = client.images.edit(model="gpt-image-2", image=("p.png", buf.getvalue(), "image/png"),
                           prompt=HOUSE_STYLE, size=size, quality="medium")
    out = Image.open(io.BytesIO(base64.b64decode(r.data[0].b64_json))).convert("RGB")
    out = out.resize((768, round(768 * out.height / out.width)))
    ob = io.BytesIO(); out.save(ob, "JPEG", quality=86, optimize=True)
    return ob.getvalue()


# ── one queue row ─────────────────────────────────────────────────────────────
def process_row(client, row):
    upload_id, entity_id, entity_name, path, lat, lng = row
    with connect() as conn, conn.cursor() as cur:
        if not entity_id:
            cur.execute(
                """insert into entities (name, is_batavia_local, source, verification_status, last_verified_by)
                   values (%s, true, 'manual', 'verified', 'manual') returning id""",
                (entity_name or "Untitled place",),
            )
            entity_id = cur.fetchone()[0]

        hero_bytes = enhance(client, storage_download(path))
        public_url = storage_upload(f"heroes/{entity_id}.jpg", hero_bytes)

        set_location(cur, entity_id, reverse_geocode(lat, lng))
        cur.execute(
            "update entities set hero=%s, verification_status='verified', updated_at=now() where id=%s",
            (Json({"url": public_url, "kind": "community", "source": "on-location photo"}), entity_id),
        )
        cur.execute("update photo_uploads set status='done', processed_at=now() where id=%s", (upload_id,))
        conn.commit()
    return entity_id


def fetch_pending():
    with connect() as c, c.cursor() as cur:
        cur.execute(
            "select id, entity_id, entity_name, storage_path, gps_lat, gps_lng "
            "from photo_uploads where status='pending' order by created_at"
        )
        return cur.fetchall()


def mark_error(upload_id, msg):
    with connect() as c, c.cursor() as cur:
        cur.execute("update photo_uploads set status='error', note=%s, processed_at=now() where id=%s",
                    (msg[:300], upload_id))
        c.commit()


def run_once(client):
    pending = fetch_pending()
    if not pending:
        print("nothing pending.")
        return 0
    print(f"processing {len(pending)} upload(s)…")
    done = 0
    for row in pending:
        try:
            eid = process_row(client, row)
            print(f"  ✓ {row[2] or eid} → styled hero set")
            done += 1
        except Exception as e:
            mark_error(row[0], f"{type(e).__name__}: {e}")
            print(f"  ✗ {row[0]}: {type(e).__name__}: {str(e)[:80]}")
    return done


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--loop", action="store_true", help="keep polling every 20s")
    args = p.parse_args()
    client = _openai()
    if args.loop:
        print("watching the capture queue (Ctrl-C to stop)…")
        while True:
            run_once(client)
            time.sleep(20)
    else:
        run_once(client)


if __name__ == "__main__":
    main()
