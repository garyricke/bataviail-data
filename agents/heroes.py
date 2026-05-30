"""Hero-image runner: give every enriched entity a hero photo.

For each entity: find a usable photo on its site (og:image from cached HTML) and
ENHANCE it into a polished editorial shot; if none is usable, GENERATE a
representative image. Each is labeled (enhanced | generated). Throttled,
resumable (skips entities that already have a hero), failure-isolated, cost-capped.

    DRY_RUN=0 python -m agents.heroes --limit 8                 # test batch
    DRY_RUN=0 python -m agents.heroes --concurrency 6           # full run
    python -m agents.heroes --limit 8                           # dry preview (no API calls)
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import io
import os
import re
import time
import urllib.parse
import urllib.request

from PIL import Image
from psycopg.types.json import Json

from agents.config import DRY_RUN
from agents.db import connect
from agents.scout import BROWSER_UA, _fetch

HERO_DIR = os.path.join(os.path.dirname(__file__), "..", "web", "heroes")
SIZE, QUALITY, MODEL = "1536x1024", "medium", "gpt-image-2"

OG_RE = re.compile(r"<meta[^>]*?og:image[^>]*?>", re.I)
CONTENT_RE = re.compile(r'content=["\']([^"\']+)["\']', re.I)

ENHANCE_PROMPT = (
    "Transform this into a polished, professionally-shot editorial photograph of "
    "the SAME real place or subject: improve lighting, color balance, sharpness and "
    "composition for a clean website hero banner. Keep it photographic and true to "
    "the original scene — do not invent a different building or add/alter text, "
    "signage, logos, or watermarks."
)

# gpt-image-1-family token rates (proxy for gpt-image-2 until officially published).
R_TEXT_IN, R_IMG_IN, R_IMG_OUT = 5 / 1e6, 10 / 1e6, 40 / 1e6


def _client():
    from openai import OpenAI
    return OpenAI()


def cost_of(usage) -> float:
    di = getattr(usage, "input_tokens_details", None)
    do = getattr(usage, "output_tokens_details", None)
    text_in = getattr(di, "text_tokens", 0) if di else 0
    img_in = getattr(di, "image_tokens", 0) if di else 0
    img_out = getattr(do, "image_tokens", usage.output_tokens) if do else usage.output_tokens
    return text_in * R_TEXT_IN + img_in * R_IMG_IN + img_out * R_IMG_OUT


# ── photo discovery ───────────────────────────────────────────────────────────
def _norm(u: str) -> str:
    return re.sub(r"^https?://(www\.)?", "", (u or "").lower()).rstrip("/")


def cached_body(cur, website: str):
    cur.execute(
        "select body from scout_cache "
        "where regexp_replace(regexp_replace(lower(url),'^https?://(www\\.)?',''),'/$','') = %s limit 1",
        (_norm(website),),
    )
    row = cur.fetchone()
    return row[0] if row else None


def og_image_url(body: str, base: str):
    for tag in OG_RE.findall(body):
        m = CONTENT_RE.search(tag)
        if m:
            return urllib.parse.urljoin(base, m.group(1).strip())
    return None


def download_photo(url: str):
    """Return a usable PIL image, or None if missing/too-small/not-an-image."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = r.read()
        img = Image.open(io.BytesIO(data)).convert("RGB")
        if img.width < 600 or img.height < 300:
            return None                      # likely a logo/icon, not a hero
        return img
    except Exception:
        return None


# ── image ops ─────────────────────────────────────────────────────────────────
def _enhance(client, img: Image.Image):
    buf = io.BytesIO()
    img.thumbnail((1536, 1536))
    img.save(buf, "PNG")
    buf.seek(0)
    r = client.images.edit(
        model=MODEL, image=("source.png", buf.getvalue(), "image/png"),
        prompt=ENHANCE_PROMPT, size=SIZE, quality=QUALITY,
    )
    return base64.b64decode(r.data[0].b64_json), r.usage


def _generate(client, prompt: str):
    r = client.images.generate(model=MODEL, prompt=prompt, size=SIZE, quality=QUALITY)
    return base64.b64decode(r.data[0].b64_json), r.usage


def gen_prompt(name, cats, summary):
    cat = (cats[0] if cats else "local business").lower()
    ctx = (summary or "")[:220]
    return (
        f"A professional editorial hero photograph representing a {cat} in a historic "
        f"Midwestern downtown (Batavia, Illinois). Context: {ctx} "
        "Warm natural light, inviting and authentic, photorealistic, high quality. "
        "No text, no logos, no watermarks, no readable signage."
    )


def save_hero(eid, png_bytes) -> str:
    os.makedirs(HERO_DIR, exist_ok=True)
    img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    img = img.resize((768, round(768 * img.height / img.width)))
    img.save(os.path.join(HERO_DIR, f"{eid}.jpg"), "JPEG", quality=82, optimize=True)
    return f"heroes/{eid}.jpg"


def set_hero(eid, url, kind, source):
    with connect() as c, c.cursor() as cur:
        cur.execute("update entities set hero=%s, updated_at=now() where id=%s",
                    (Json({"url": url, "kind": kind, "source": source}), eid))
        c.commit()


# ── orchestration ─────────────────────────────────────────────────────────────
def fetch_targets(limit, local_only):
    where = ["e.last_verified_by like 'claude%'", "e.hero is null", "coalesce(trim(e.website),'')<>''"]
    if local_only:
        where.append("e.is_batavia_local")
    sql = f"""
        select e.id, e.name, trim(e.website),
               coalesce((select array_agg(c.name) from entity_categories ec
                         join categories c on c.id=ec.category_id where ec.entity_id=e.id), '{{}}'),
               e.summary
        from entities e where {' and '.join(where)}
        order by case e.membership_level when 'Platinum' then 0 when 'Pro' then 0 when 'Gold' then 1 else 2 end, e.name
        {'limit ' + str(limit) if limit else ''}
    """
    with connect() as c, c.cursor() as cur:
        cur.execute(sql)
        return [dict(zip(["id", "name", "website", "cats", "summary"], r)) for r in cur.fetchall()]


def process_one(client, e):
    """Returns (kind, cost). Enhance if a good photo exists, else generate."""
    with connect() as c, c.cursor() as cur:
        body = cached_body(cur, e["website"])
    if body is None:
        try:
            _, _, body, _ = _fetch(e["website"] if e["website"].startswith("http") else "http://" + e["website"])
        except Exception:
            body = ""
    og = og_image_url(body, e["website"]) if body else None
    photo = download_photo(og) if og else None

    if photo is not None:
        png, usage = _enhance(client, photo)
        kind, source = "enhanced", og
    else:
        png, usage = _generate(client, gen_prompt(e["name"], e["cats"], e["summary"]))
        kind, source = "generated", None

    url = save_hero(e["id"], png)
    set_hero(e["id"], url, kind, source)
    return kind, cost_of(usage)


async def run(args):
    targets = fetch_targets(args.limit, args.local_only)
    mode = "DRY-RUN (no API calls)" if DRY_RUN else f"LIVE → {MODEL} {QUALITY}"
    print(f"\n=== Hero images — {mode} ===")
    print(f"targets: {len(targets)} | concurrency {args.concurrency} | cost cap ${args.cost_cap}\n")
    if not targets or DRY_RUN:
        for e in targets[:20]:
            print(f"  would process: {e['name']}")
        if DRY_RUN:
            print("\nDRY-RUN: re-run with DRY_RUN=0 to create images.")
        return

    client = _client()
    state = {"total": len(targets), "enhanced": 0, "generated": 0, "failed": 0, "cost": 0.0}
    sem = asyncio.Semaphore(args.concurrency)
    t0 = time.monotonic()

    async def work(e):
        async with sem:
            if state["cost"] >= args.cost_cap:
                return
            i = state["enhanced"] + state["generated"] + state["failed"] + 1
            try:
                kind, cost = await asyncio.to_thread(process_one, client, e)
                state[kind] += 1
                state["cost"] += cost
                print(f"[{i:>3}/{state['total']}] {kind:<9} {e['name'][:44]:<44} ${state['cost']:.2f}")
            except Exception as ex:
                state["failed"] += 1
                print(f"[{i:>3}/{state['total']}] FAILED    {e['name'][:44]:<44} {type(ex).__name__}: {str(ex)[:60]}")

    await asyncio.gather(*(work(e) for e in targets))
    print("\n" + "─" * 64)
    print(f"enhanced: {state['enhanced']} | generated: {state['generated']} | failed: {state['failed']}")
    print(f"cost: ${state['cost']:.2f} | time: {(time.monotonic()-t0)/60:.1f} min")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--concurrency", type=int, default=6)
    p.add_argument("--cost-cap", type=float, default=30.0)
    p.add_argument("--local-only", action="store_true")
    asyncio.run(run(p.parse_args()))


if __name__ == "__main__":
    main()
