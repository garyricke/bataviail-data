"""Daily events refresher — keeps the directory's upcoming events fresh.

For every entity with a website it does a cheap re-scout (HTTP + change detection
via scout_cache, no Brave search). It only spends an LLM call when the page that
holds events actually CHANGED, and then uses the cheap model (Haiku) to re-extract
dated events, writing ONLY the events (via apply_events — never touching deep-enrich
state). Past events need no cleanup: the entity_full view already hides anything
with starts_at < now().

    DRY_RUN=0 python -m agents.refresh_events --limit 5     # live smoke test
    DRY_RUN=0 python -m agents.refresh_events               # live, everything due

In DRY_RUN (default) it writes nothing.
"""
from __future__ import annotations

import argparse
import asyncio
import time

from agents.config import DRY_RUN, MODEL_CHEAP
from agents.db import apply_events, connect
from agents.enrich import enrich
from agents.scout import scout

# Haiku 4.5 pricing ($/token).
IN_RATE, OUT_RATE = 1.0 / 1e6, 5.0 / 1e6


def cost_of(usage: dict) -> float:
    return usage.get("input", 0) * IN_RATE + usage.get("output", 0) * OUT_RATE


def fetch_targets(limit: int, local_only: bool):
    where = ["coalesce(trim(e.website),'') <> ''", "coalesce(f.failure_streak,0) < 3"]
    if local_only:
        where.append("e.is_batavia_local")
    sql = f"""
        select e.id, e.name, e.member_id, trim(e.website), e.membership_level,
               true as has_hours,
               coalesce((select array_agg(platform) from entity_social s where s.entity_id = e.id), '{{}}') as socials
        from entities e
        left join entity_freshness f on f.entity_id = e.id
        where {' and '.join(where)}
        order by case e.membership_level
                   when 'Platinum' then 0 when 'Pro' then 0 when 'Gold' then 1 else 2 end, e.name
        {'limit ' + str(limit) if limit else ''}
    """
    with connect() as c, c.cursor() as cur:
        cur.execute(sql)
        cols = ["id", "name", "member_id", "website", "membership_level", "has_hours", "socials"]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def record_failure(eid):
    with connect() as c, c.cursor() as cur:
        cur.execute(
            """insert into entity_freshness (entity_id, last_checked_at, failure_streak)
               values (%s, now(), 1)
               on conflict (entity_id) do update set
                 last_checked_at = now(), failure_streak = entity_freshness.failure_streak + 1""",
            (eid,),
        )
        c.commit()


def _should_extract(bundle) -> bool:
    """Spend an LLM call only when the page holding events plausibly changed:
    a changed dedicated events page, or — when there's no separate events page —
    a changed homepage (events may be listed inline)."""
    if bundle.events_url:
        return bundle.events_changed
    return bundle.changed


async def worker(entity, sem, state, cap):
    async with sem:
        if cap and state["cost"] >= cap:
            state["skipped_cap"] += 1
            return
        i = state["done"] + state["failed"] + state["skipped_unchanged"] + state["skipped_cap"] + 1
        try:
            bundle = await scout(entity, search=False)
            if not _should_extract(bundle) or not (bundle.events_text or bundle.homepage_text):
                state["skipped_unchanged"] += 1
                return
            update = await enrich(entity, bundle, deep=False)
            evs = update.fields.get("events", [])
            n = await asyncio.to_thread(apply_events, entity["id"], evs, update.model)
            state["cost"] += cost_of(update.usage)
            state["done"] += 1
            state["events"] += n
            print(f"[{i:>3}/{state['total']}] ✓ {entity['name'][:42]:<42} "
                  f"{('· ' + str(n) + ' events') if n else '· no dated events':<18} ${state['cost']:.3f}")
        except Exception as e:
            await asyncio.to_thread(record_failure, entity["id"])
            state["failed"] += 1
            print(f"[{i:>3}/{state['total']}] ✗ {entity['name'][:42]:<42} {type(e).__name__}: {str(e)[:50]}")


async def run(args):
    targets = fetch_targets(args.limit, args.local_only)
    mode = "DRY-RUN (no writes)" if DRY_RUN else f"LIVE → {MODEL_CHEAP}"
    print(f"\n=== Events refresh — {mode} ===")
    print(f"candidates: {len(targets)}  |  concurrency {args.concurrency}  |  cost cap ${args.cost_cap}")
    print("(LLM call only fires on a changed events/calendar page)\n")
    if not targets:
        print("Nothing to do.")
        return

    state = {"total": len(targets), "done": 0, "failed": 0,
             "skipped_unchanged": 0, "skipped_cap": 0, "cost": 0.0, "events": 0}
    sem = asyncio.Semaphore(args.concurrency)
    t0 = time.monotonic()
    await asyncio.gather(*(worker(e, sem, state, args.cost_cap) for e in targets))
    dt = time.monotonic() - t0

    print("\n" + "─" * 70)
    print(f"changed+extracted: {state['done']}  unchanged(skipped): {state['skipped_unchanged']}  "
          f"failed: {state['failed']}  cap-skipped: {state['skipped_cap']}")
    print(f"events written/refreshed: {state['events']}  |  cost: ${state['cost']:.3f}  |  time: {dt/60:.1f} min")
    if DRY_RUN:
        print("DRY-RUN: re-run with DRY_RUN=0 to write for real.")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=0, help="max entities to check (0 = all)")
    p.add_argument("--concurrency", type=int, default=6)
    p.add_argument("--cost-cap", type=float, default=5.0, help="USD; stop launching past this")
    p.add_argument("--local-only", action="store_true", help="Batavia-local entities only")
    asyncio.run(run(p.parse_args()))


if __name__ == "__main__":
    main()
