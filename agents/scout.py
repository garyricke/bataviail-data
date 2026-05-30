"""Scout: gather raw signals about an entity (homepage, search, social).

DRY_RUN synthesizes a deterministic bundle (no network, no cost). `_scout_live`
does the real thing: fetch the homepage, extract socials/contacts via regex, run
an optional Brave search, and cache the raw body in scout_cache for change
detection. Run a single live scout with `python -m agents.scout_one`.
"""
from __future__ import annotations

import asyncio
import collections
import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from agents.config import DRY_RUN

KNOWN_PLATFORMS = ["facebook", "instagram", "linkedin", "x"]
UA = "Mozilla/5.0 (compatible; BataviaILBot/0.1; +https://batavia.example/bot)"

SOCIAL_RE = re.compile(
    r'https?://(?:www\.)?(facebook|instagram|linkedin|twitter|x|youtube|tiktok)\.com/[^\s"\'<>)]+',
    re.I,
)
EVENTS_LINK_RE = re.compile(
    r'<a\b[^>]*?href=["\']([^"\']+)["\'][^>]*?>(.*?)</a>', re.I | re.S)
EVENTS_HINT_RE = re.compile(r'event|calendar|happening|upcoming|workshops?|classes', re.I)
EMAIL_RE = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}')
PHONE_RE = re.compile(r'\(?\b\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b')
TITLE_RE = re.compile(r'<title[^>]*>(.*?)</title>', re.I | re.S)


@dataclass
class ScoutBundle:
    entity_id: str
    changed: bool                        # cheap freshness check result
    source: str = "dry-run"
    final_url: str = ""
    status: int = 0
    title: str = ""
    homepage_text: str = ""
    events_url: str = ""
    events_text: str = ""
    brand_evidence: dict = field(default_factory=dict)
    search_snippets: list[str] = field(default_factory=list)
    discovered_hours: list[dict] = field(default_factory=list)
    discovered_social: dict = field(default_factory=dict)
    discovered_contacts: dict = field(default_factory=dict)
    discovered_news: list[str] = field(default_factory=list)


# ── DRY-RUN synthesis ─────────────────────────────────────────────────────────
def _seed(entity) -> int:
    return int(hashlib.sha1(str(entity["id"]).encode()).hexdigest(), 16)


def _synthesize(entity) -> ScoutBundle:
    s = _seed(entity)
    opens = ["08:00", "09:00", "10:00"][s % 3]
    closes = ["17:00", "18:00", "20:00"][(s // 3) % 3]
    hours = []
    if not entity["has_hours"]:
        for dow in range(1, 6):
            hours.append({"day_of_week": dow, "opens": opens, "closes": closes})
    missing = [p for p in KNOWN_PLATFORMS if p not in entity["socials"]]
    social = {}
    if missing:
        plat = missing[s % len(missing)]
        handle = entity["name"].lower().replace(" ", "").replace(",", "")[:20]
        social = {plat: f"https://{plat}.com/{handle}"}
    return ScoutBundle(
        entity_id=entity["id"], changed=True, source="dry-run",
        homepage_text=f"[synthetic homepage text for {entity['name']}]",
        search_snippets=[f"{entity['name']} — Batavia, IL"],
        discovered_hours=hours, discovered_social=social,
        discovered_news=[f"[synthetic] {entity['name']} featured in a Batavia spotlight"],
    )


# ── LIVE helpers ──────────────────────────────────────────────────────────────
BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def _do_fetch(url, ua, ctx, timeout):
    req = urllib.request.Request(url, headers={
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Encoding": "identity",  # avoid gzip so body is plain text
    })
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
        # Strip NUL (0x00) here so nothing downstream (cache, text, brand) carries
        # bytes Postgres text columns reject.
        body = r.read().decode("utf-8", errors="replace").replace("\x00", "")
        return r.geturl(), r.status, body, r.headers.get("ETag")


def _legacy_ssl_ctx():
    import ssl
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        ctx.minimum_version = ssl.TLSVersion.TLSv1
    except Exception:
        pass
    try:
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")  # allow old servers' weak ciphers
    except Exception:
        pass
    return ctx


def _fetch(url: str, timeout: int = 15):
    """Return (final_url, status, body, etag). Falls back to a browser UA on 403
    and to permissive TLS on legacy-SSL handshake failures."""
    try:
        return _do_fetch(url, UA, None, timeout)
    except urllib.error.HTTPError as e:
        if e.code in (403, 406, 429):
            return _do_fetch(url, BROWSER_UA, None, timeout)  # some sites block bot UAs
        raise
    except urllib.error.URLError as e:
        reason = str(getattr(e, "reason", e)).upper()
        if "SSL" in reason or "CERTIFICATE" in reason or "EOF" in reason:
            return _do_fetch(url, BROWSER_UA, _legacy_ssl_ctx(), timeout)
        raise


def _html_to_text(html: str) -> str:
    html = re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', html, flags=re.I | re.S)
    text = re.sub(r'<[^>]+>', ' ', html)
    text = re.sub(r'&[a-z]+;', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()


def _extract_socials(html: str) -> dict:
    out = {}
    for m in SOCIAL_RE.finditer(html):
        plat = m.group(1).lower()
        plat = "x" if plat in ("twitter", "x") else plat
        out.setdefault(plat, m.group(0).rstrip('/").,'))
    return out


EMAIL_PLACEHOLDERS = ("domain.com", "example.com", "example.org", "yourname",
                      "your@email", "email@", "sentry.io", "wixpress.com")


def _extract_contacts(html: str, text: str) -> dict:
    out = {}
    emails = [
        e for e in EMAIL_RE.findall(html)
        if not e.lower().endswith((".png", ".jpg", ".gif"))
        and not any(p in e.lower() for p in EMAIL_PLACEHOLDERS)
    ]
    if emails:
        out["email"] = emails[0]
    phones = PHONE_RE.findall(text)
    if phones:
        out["phone"] = phones[0]
    return out


# ── Brand-signal extraction ───────────────────────────────────────────────────
THEME_RE = re.compile(r'<meta[^>]*?theme-color[^>]*?>', re.I)
CONTENT_RE = re.compile(r'content=["\']([^"\']+)["\']', re.I)
GFONT_FAMILY_RE = re.compile(r'family=([A-Za-z0-9 +]+)', re.I)
FONTFAM_RE = re.compile(r'font-family\s*:\s*([^;{}"\']+)', re.I)
HEX_RE = re.compile(r'#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b')
CSSVAR_RE = re.compile(
    r'(--[\w-]*(?:colou?r|primary|secondary|accent|brand|theme)[\w-]*)\s*:\s*'
    r'(#[0-9a-fA-F]{3,8}|rgba?\([^)]+\))', re.I)
LINK_RE = re.compile(r'<link\b[^>]*>', re.I)
HREF_RE = re.compile(r'href=["\']([^"\']+)["\']', re.I)


def _hex6(h: str):
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return "#" + h.lower() if len(h) == 6 else None


def _interesting(hex6: str) -> bool:
    """Drop near-grays, near-white and near-black — keep saturated brand colors."""
    r, g, b = int(hex6[1:3], 16), int(hex6[3:5], 16), int(hex6[5:7], 16)
    mx, mn = max(r, g, b), min(r, g, b)
    if mx - mn < 24:
        return False                       # gray
    if mx > 245 and mn > 230:
        return False                       # near white
    return True


def _clean_font(decl: str):
    first = decl.split(",")[0].strip().strip("'\"")
    low = first.lower()
    if not first or low in ("inherit", "initial", "unset") or first.startswith(("var(", "-")):
        return None
    if low in ("sans-serif", "serif", "monospace", "system-ui"):
        return None
    return first


def _brand_signals(text: str, is_html: bool) -> dict:
    sig = {"fonts": [], "colors": collections.Counter(), "vars": {}, "theme": None}
    if is_html:
        for tag in THEME_RE.findall(text):
            m = CONTENT_RE.search(tag)
            if m:
                sig["theme"] = m.group(1).strip()
                break
        for fam in GFONT_FAMILY_RE.findall(text):
            f = fam.replace("+", " ").strip()
            if f and f not in sig["fonts"]:
                sig["fonts"].append(f)
    for decl in FONTFAM_RE.findall(text):
        f = _clean_font(decl)
        if f and f not in sig["fonts"]:
            sig["fonts"].append(f)
    for h in HEX_RE.findall(text):
        h6 = _hex6(h)
        if h6 and _interesting(h6):
            sig["colors"][h6] += 1
    for name, val in CSSVAR_RE.findall(text):
        sig["vars"][name.lower()] = val.strip()
    return sig


def _first_stylesheet(html: str, base_url: str) -> str:
    for m in LINK_RE.finditer(html):
        tag = m.group(0)
        if "stylesheet" in tag.lower():
            hm = HREF_RE.search(tag)
            if hm:
                u = urllib.parse.urljoin(base_url, hm.group(1))
                if ".css" in u.lower():
                    return u
    return ""


def _find_events_url(html: str, base_url: str) -> str:
    """Pick the best same-site events/calendar link from the homepage, if any."""
    best = None
    for m in EVENTS_LINK_RE.finditer(html):
        href, text = m.group(1), re.sub(r'<[^>]+>', '', m.group(2))
        if href.startswith(("mailto:", "tel:", "#", "javascript:")):
            continue
        if EVENTS_HINT_RE.search(href) or EVENTS_HINT_RE.search(text):
            absu = urllib.parse.urljoin(base_url, href)
            if urllib.parse.urlparse(absu).netloc == urllib.parse.urlparse(base_url).netloc:
                # Prefer a path that literally contains 'event' or 'calendar'.
                score = 2 if re.search(r'event|calendar', absu, re.I) else 1
                if best is None or score > best[0]:
                    best = (score, absu)
    return best[1] if best else ""


def _brave_search(query: str, n: int = 3) -> list[str]:
    key = os.environ.get("BRAVE_API_KEY")
    if not key:
        return []  # graceful: skip search when no key
    url = "https://api.search.brave.com/res/v1/web/search?q=" + urllib.parse.quote(query)
    req = urllib.request.Request(url, headers={"X-Subscription-Token": key, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
        return [f"{x.get('title','')} - {x.get('description','')}"
                for x in data.get("web", {}).get("results", [])[:n]]
    except Exception:
        return []  # search is best-effort; never let it break the scout


def _cache_get(url: str):
    from agents.db import connect
    with connect() as c, c.cursor() as cur:
        cur.execute("select content_hash from scout_cache where url=%s", (url,))
        row = cur.fetchone()
    return row[0] if row else None


def _cache_put(url, status, etag, content_hash, body):
    from agents.db import connect
    with connect() as c, c.cursor() as cur:
        cur.execute("""
            insert into scout_cache (url, status, etag, content_hash, body, fetched_at)
            values (%s,%s,%s,%s,%s, now())
            on conflict (url) do update set
              status=excluded.status, etag=excluded.etag,
              content_hash=excluded.content_hash, body=excluded.body,
              fetched_at=now()
        """, (url, status, etag, content_hash, body[:500_000]))
        c.commit()


async def _scout_live(entity) -> ScoutBundle:
    url = entity["website"]
    if not url:
        return ScoutBundle(entity_id=entity["id"], changed=False, source="live",
                           discovered_news=["no website on record — needs discovery"])
    if not url.startswith("http"):
        url = "http://" + url

    final_url, status, body, etag = await asyncio.to_thread(_fetch, url)
    content_hash = hashlib.sha256(body.encode("utf-8", "replace")).hexdigest()
    prev = _cache_get(final_url)
    changed = prev != content_hash
    _cache_put(final_url, status, etag, content_hash, body)

    text = _html_to_text(body)
    title_m = TITLE_RE.search(body)
    socials = {p: u for p, u in _extract_socials(body).items() if p not in entity["socials"]}
    snippets = await asyncio.to_thread(_brave_search, f'{entity["name"]} Batavia IL hours')

    # Brand signals: homepage HTML + first linked stylesheet (best-effort).
    brand = _brand_signals(body, is_html=True)
    css_href = _first_stylesheet(body, final_url)
    if css_href:
        try:
            _, _, css, _ = await asyncio.to_thread(_fetch, css_href)
            css_sig = _brand_signals(css[:60000], is_html=False)
            brand["colors"] += css_sig["colors"]
            for f in css_sig["fonts"]:
                if f not in brand["fonts"]:
                    brand["fonts"].append(f)
            brand["vars"].update(css_sig["vars"])
        except Exception:
            pass
    brand_evidence = {
        "theme_color": brand["theme"],
        "fonts": brand["fonts"][:6],
        "css_vars": dict(list(brand["vars"].items())[:8]),
        "top_colors": [f"{c} (x{n})" for c, n in brand["colors"].most_common(8)],
    }

    # Look for an events/calendar page and fetch it (best-effort, cached).
    events_url, events_text = "", ""
    found = _find_events_url(body, final_url)
    if found and found.rstrip("/") != final_url.rstrip("/"):
        try:
            ev_final, ev_status, ev_body, ev_etag = await asyncio.to_thread(_fetch, found)
            _cache_put(ev_final, ev_status, ev_etag,
                       hashlib.sha256(ev_body.encode("utf-8", "replace")).hexdigest(), ev_body)
            events_url, events_text = ev_final, _html_to_text(ev_body)[:5000]
        except Exception:
            pass  # events page is optional; never fail the scout over it

    return ScoutBundle(
        entity_id=entity["id"], changed=changed, source="live",
        final_url=final_url, status=status,
        title=(title_m.group(1).strip() if title_m else ""),
        homepage_text=text[:4000],
        events_url=events_url, events_text=events_text,
        brand_evidence=brand_evidence,
        search_snippets=snippets,
        discovered_social=socials,
        discovered_contacts=_extract_contacts(body, text),
    )


async def scout(entity) -> ScoutBundle:
    """Cheap freshness check first; only deep-scout on detected change."""
    if DRY_RUN:
        await asyncio.sleep(0)
        return _synthesize(entity)
    return await _scout_live(entity)
