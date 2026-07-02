"""Logo pipeline: migrate chamber logos + harvest missing ones → Cloudinary.

Two jobs, one pass:

1. **Migrate** the ~140 chamber logos already in `entities.logo_url` (hot-linked
   ChamberMaster CDN URLs) onto Cloudinary — our image standard — so we no longer
   depend on a third-party CDN and everything is `f_auto,q_auto` optimized.

2. **Harvest** a logo for entities that have none, from the entity's own website:
   apple-touch-icon → svg/mask icon → largest rel=icon → og:image → favicon →
   (last resort) Google's favicon service. HTML comes from the `scout_cache` we
   already fetched, falling back to a live GET. Best candidate wins.

Result lands at a Cloudinary delivery URL in `entities.logo_url`; `brand.logo_source`
records where it came from (chamber vs apple-touch-icon vs favicon…) so the frontend
can treat trusted chamber logos differently from scraped favicons.

Idempotent + resumable: entities whose `logo_url` is already a Cloudinary URL are
skipped. Honors DRY_RUN (default ON): reads/harvest-analysis still run, but nothing
is uploaded to Cloudinary or written to the DB — it prints what it *would* do.

Usage:
  python -m agents.logos                      # dry-run preview (no writes)
  DRY_RUN=0 python -m agents.logos            # live: upload + write
  DRY_RUN=0 python -m agents.logos --only chamber --limit 5
"""
from __future__ import annotations

import argparse
import io
import os
import re
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

import psycopg
from dotenv import load_dotenv

load_dotenv(override=True)  # .env authoritative (CLOUDINARY_URL, DATABASE_URL)

# cloudinary auto-configures from the CLOUDINARY_URL env var on import.
import cloudinary          # noqa: E402
import cloudinary.uploader  # noqa: E402
from PIL import Image      # noqa: E402

DRY_RUN = os.environ.get("DRY_RUN", "1") != "0"
UA = "Mozilla/5.0 (compatible; BataviaILLogoBot/1.0; +https://batavia-data.netlify.app)"
CLOUD_FOLDER = "bataviail/logos"
CLOUDINARY_HOST = "res.cloudinary.com"


# ── HTTP ──────────────────────────────────────────────────────────────────────
def http_get(url, timeout=15, max_bytes=6_000_000):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, (r.headers.get("Content-Type") or ""), r.read(max_bytes)


def _norm(website):
    w = (website or "").strip()
    if not w:
        return ""
    if not re.match(r"^https?://", w, re.I):
        w = "https://" + w
    return w


def _key(url):
    """Loose identity for matching a website to a scout_cache row: host+path, no
    scheme/www/trailing-slash/query."""
    try:
        p = urllib.parse.urlsplit(_norm(url))
        host = p.netloc.lower().removeprefix("www.")
        path = p.path.rstrip("/")
        return host + path
    except Exception:
        return (url or "").lower()


# ── Logo-candidate extraction from HTML ────────────────────────────────────────
_TAG = re.compile(r"<(link|meta)\b[^>]*>", re.I)
_ATTR = re.compile(r'([a-zA-Z:-]+)\s*=\s*"([^"]*)"|([a-zA-Z:-]+)\s*=\s*\'([^\']*)\'')


def _attrs(tag):
    out = {}
    for m in _ATTR.finditer(tag):
        k = (m.group(1) or m.group(3) or "").lower()
        v = m.group(2) if m.group(2) is not None else (m.group(4) or "")
        out[k] = v.strip()
    return out


def _size_of(a):
    m = re.search(r"(\d+)x(\d+)", a.get("sizes", "") or a.get("href", ""))
    return int(m.group(1)) if m else 0


def candidates(html, base_url):
    """Return [(priority, source, absolute_url)] best-first."""
    out = []
    for tag in _TAG.finditer(html or ""):
        raw = tag.group(0)
        a = _attrs(raw)
        rel = (a.get("rel") or "").lower()
        prop = (a.get("property") or a.get("name") or "").lower()
        href = a.get("href") or a.get("content")
        if not href:
            continue
        absu = urllib.parse.urljoin(base_url, href)
        typ = (a.get("type") or "").lower()
        sz = _size_of(a)
        if "apple-touch-icon" in rel:
            out.append((300 + sz, "apple-touch-icon", absu))
        elif "mask-icon" in rel or (("icon" in rel) and ("svg" in typ or absu.lower().endswith(".svg"))):
            out.append((250, "svg-icon", absu))
        elif "icon" in rel:
            out.append((150 + sz if sz else 120, "icon", absu))
        elif prop in ("og:image", "og:image:url", "twitter:image", "twitter:image:src"):
            out.append((90, "og-image", absu))
    # Guaranteed fallbacks (host favicon, then Google's service).
    p = urllib.parse.urlsplit(base_url)
    if p.netloc:
        out.append((40, "favicon", f"{p.scheme}://{p.netloc}/favicon.ico"))
        out.append((20, "favicon-google",
                    f"https://www.google.com/s2/favicons?sz=128&domain={p.netloc}"))
    # de-dup keeping best priority, then sort
    best = {}
    for pri, src, u in out:
        if u not in best or pri > best[u][0]:
            best[u] = (pri, src)
    return sorted([(v[0], v[1], u) for u, v in best.items()], reverse=True)


def valid_image(data):
    """Return (ok, min_dim) — opens with PIL, rejects non-images."""
    try:
        im = Image.open(io.BytesIO(data))
        im.verify()
        w, h = im.size
        return True, min(w, h)
    except Exception:
        return False, 0


def harvest(website, html):
    """Pick + download the best logo for a site. Returns (bytes, source) or (None, note)."""
    base = _norm(website)
    if html is None:
        try:
            st, ct, data = http_get(base)
            html = data.decode("utf-8", "ignore") if "html" in ct.lower() else ""
        except Exception as e:
            return None, f"no-html ({type(e).__name__})"
    cands = candidates(html, base)
    if not cands:
        return None, "no-candidates"
    fallback = None  # best image that opened but was small
    for pri, src, url in cands:
        try:
            st, ct, data = http_get(url, max_bytes=4_000_000)
            if st != 200 or not data:
                continue
            ok, dim = valid_image(data)
            if not ok:
                continue
            if dim >= 48:
                return data, src
            if fallback is None:
                fallback = (data, src)
        except Exception:
            continue
    if fallback:
        return fallback
    return None, "no-usable-image"


# ── Cloudinary ─────────────────────────────────────────────────────────────────
def upload(source, public_id):
    """source = URL (chamber) or bytes (harvested). Returns optimized delivery URL.

    Built by injecting the transformation into Cloudinary's own secure_url, so the
    extension is always the real stored format (f_auto then negotiates webp/avif)."""
    payload = io.BytesIO(source) if isinstance(source, (bytes, bytearray)) else source
    res = cloudinary.uploader.upload(
        payload, folder=CLOUD_FOLDER, public_id=public_id, overwrite=True,
        resource_type="image", unique_filename=False, invalidate=True,
    )
    tx = "c_limit,f_auto,q_auto,w_400/"
    return res["secure_url"].replace("/upload/", "/upload/" + tx, 1)


# ── DB ─────────────────────────────────────────────────────────────────────────
def connect():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL not set — fill .env.")
    return psycopg.connect(url)


def load_entities(cur):
    cur.execute("select id, name, coalesce(website,''), coalesce(logo_url,'') from entities order by name")
    return [{"id": r[0], "name": r[1], "website": r[2], "logo_url": r[3]} for r in cur.fetchall()]


def load_cache(cur, websites):
    keys = list({_key(w) for w in websites if w})
    if not keys:
        return {}
    # Pull candidate rows, then match by loose key in Python (cache urls vary).
    cur.execute("select url, body from scout_cache where body is not null")
    m = {}
    for url, body in cur.fetchall():
        k = _key(url)
        if k in keys and k not in m:
            m[k] = body
    return m


# ── Orchestration ──────────────────────────────────────────────────────────────
def classify(e):
    lu = e["logo_url"]
    if CLOUDINARY_HOST in lu:
        return "done", None
    if lu.startswith("http"):
        return "chamber", lu
    if e["website"].strip():
        return "harvest", e["website"]
    return "skip", None


def worker(e, kind, ref, cache):
    try:
        pid = str(e["id"])
        if kind == "chamber":
            url = upload(ref, pid) if not DRY_RUN else "(dry) " + ref
            return {"id": e["id"], "name": e["name"], "ok": True, "url": url, "source": "chamber"}
        html = cache.get(_key(ref))
        data, src = harvest(ref, html)
        if not data:
            return {"id": e["id"], "name": e["name"], "ok": False, "note": src}
        url = upload(data, pid) if not DRY_RUN else f"(dry) harvested:{src}"
        return {"id": e["id"], "name": e["name"], "ok": True, "url": url, "source": src}
    except Exception as ex:
        return {"id": e["id"], "name": e["name"], "ok": False, "note": f"{type(ex).__name__}: {ex}"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["chamber", "harvest", "all"], default="all")
    ap.add_argument("--limit", type=int, default=0, help="cap tasks (0 = no cap)")
    ap.add_argument("--concurrency", type=int, default=8)
    args = ap.parse_args()

    conn = connect()
    cur = conn.cursor()
    ents = load_entities(cur)

    tasks = []
    counts = {"done": 0, "skip": 0, "chamber": 0, "harvest": 0}
    for e in ents:
        kind, ref = classify(e)
        counts[kind] = counts.get(kind, 0) + 1
        if kind in ("done", "skip"):
            continue
        if args.only != "all" and kind != args.only:
            continue
        tasks.append((e, kind, ref))
    if args.limit:
        tasks = tasks[: args.limit]

    print(f"Entities: {len(ents)} | already-cloudinary: {counts['done']} | "
          f"no-source: {counts['skip']} | chamber-to-migrate: {counts['chamber']} | "
          f"harvest-targets: {counts['harvest']}")
    print(f"Running {len(tasks)} task(s) · concurrency={args.concurrency} · "
          f"{'DRY-RUN (no writes)' if DRY_RUN else 'LIVE'}\n")

    cache = load_cache(cur, [ref for (_, k, ref) in tasks if k == "harvest"])

    done = fail = 0
    by_source = {}
    with ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        futs = {ex.submit(worker, e, k, ref, cache): e for (e, k, ref) in tasks}
        for fut in as_completed(futs):
            r = fut.result()
            if r["ok"]:
                by_source[r["source"]] = by_source.get(r["source"], 0) + 1
                if not DRY_RUN:
                    cur.execute(
                        "update entities set logo_url=%s, "
                        "brand = coalesce(brand,'{}'::jsonb) || jsonb_build_object('logo_source',%s::text) "
                        "where id=%s",
                        (r["url"], r["source"], r["id"]),
                    )
                    conn.commit()
                done += 1
                print(f"  ✓ {r['name'][:42]:42}  {r['source']:16} {r['url'][:70]}")
            else:
                fail += 1
                print(f"  ✗ {r['name'][:42]:42}  {r.get('note','')}")

    print(f"\nDone. success={done} fail={fail}")
    print("by source:", ", ".join(f"{k}={v}" for k, v in sorted(by_source.items())))
    if DRY_RUN:
        print("\n(DRY-RUN — nothing uploaded or written. Re-run with DRY_RUN=0 to apply.)")
    conn.close()


if __name__ == "__main__":
    main()
