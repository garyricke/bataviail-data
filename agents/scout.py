"""Scout: gather raw signals about an entity (homepage, search, social).

DRY_RUN synthesizes a deterministic bundle from what we already know — no network,
no cost — so the downstream enrich/apply steps have realistic input. The real
implementation (Brave Search + homepage fetch + cache by URL/etag) slots into
`_scout_live` later.
"""
from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass, field

from agents.config import DRY_RUN

KNOWN_PLATFORMS = ["facebook", "instagram", "linkedin", "x"]


@dataclass
class ScoutBundle:
    entity_id: str
    changed: bool                      # cheap freshness check result
    homepage_text: str = ""
    search_snippets: list[str] = field(default_factory=list)
    discovered_hours: list[dict] = field(default_factory=list)
    discovered_social: dict = field(default_factory=dict)
    discovered_news: list[str] = field(default_factory=list)
    source: str = "dry-run"


def _seed(entity) -> int:
    return int(hashlib.sha1(str(entity["id"]).encode()).hexdigest(), 16)


def _synthesize(entity) -> ScoutBundle:
    """Deterministic fake 'discoveries' derived from the entity's own gaps."""
    s = _seed(entity)
    opens = ["08:00", "09:00", "10:00"][s % 3]
    closes = ["17:00", "18:00", "20:00"][(s // 3) % 3]

    hours = []
    if not entity["has_hours"]:  # fill the universal gap
        for dow in range(1, 6):  # Mon–Fri
            hours.append({"day_of_week": dow, "opens": opens, "closes": closes})

    # Propose a social platform the entity doesn't already have.
    missing = [p for p in KNOWN_PLATFORMS if p not in entity["socials"]]
    social = {}
    if missing:
        plat = missing[s % len(missing)]
        handle = entity["name"].lower().replace(" ", "").replace(",", "")[:20]
        social = {plat: f"https://{plat}.com/{handle}"}

    news = [f"[synthetic] {entity['name']} featured in a Batavia community spotlight"]
    return ScoutBundle(
        entity_id=entity["id"], changed=True,
        homepage_text=f"[synthetic homepage text for {entity['name']}]",
        search_snippets=[f"{entity['name']} — Batavia, IL"],
        discovered_hours=hours, discovered_social=social, discovered_news=news,
    )


async def _scout_live(entity) -> ScoutBundle:  # pragma: no cover - Phase 0b real path
    raise NotImplementedError(
        "Live scout (Brave Search + homepage fetch + scout_cache) lands here once "
        "BRAVE_API_KEY is set and DRY_RUN is off."
    )


async def scout(entity) -> ScoutBundle:
    """Cheap freshness check first; only deep-scout on detected change."""
    await asyncio.sleep(0)  # placeholder for real async I/O
    if DRY_RUN:
        return _synthesize(entity)
    return await _scout_live(entity)
