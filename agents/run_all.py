"""Throttled, resumable enrichment runner for the whole directory.

Scouts + enriches + writes every eligible entity (has a website, not yet
deep-enriched, under the failure cap), with a concurrency cap, a hard cost cap,
and per-entity failure isolation. Re-runnable: already-enriched entities are
skipped, so an interrupted run resumes where it left off.

    DRY_RUN=0 python -m agents.run_all --limit 5      # live, first 5 (smoke test)
    DRY_RUN=0 python -m agents.run_all                # live, everything remaining
    DRY_RUN=0 python -m agents.run_all --local-only --concurrency 6 --cost-cap 15

In DRY_RUN (default) it previews against synthesized data and writes nothing.
"""
from __future__ import annotations

import argparse
import asyncio
import time

from agents.config import DRY_RUN, MODEL_DEEP
from agents.db import apply_update, connect
from agents.enrich import enrich
from agents.scout import scout

# Sonnet 4.6 pricing ($/token). Cache not active at this prefix size.
IN_RATE, OUT_RATE = 3.0 / 1e6, 15.0 / 1e6


def cost_of(usage: dict) -> float:
    return usage.get("input", 0) * IN_RATE + usage.get("output", 0) * OUT_RATE


def fetch_targets(limit: int, local_only: bool, refresh: bool):
    where = ["coalesce(trim(e.website),'') <> ''", "coalesce(f.failure_streak,0) < 3"]
    if not refresh:
        where.append("f.last_deep_enriched_at is null")
    if local_only:
        where.append("e.is_batavia_local")
    sql = f"""
        select e.id, e.name, e.member_id, trim(e.website), e.membership_level,
               (select count(*) > 0 from entity_hours h where h.entity_id = e.id) as has_hours,
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


async def worker(entity, sem, state, cap):
    async with sem:
        if cap and state["cost"] >= cap:
            state["skipped"] += 1
            return
        i = state["done"] + state["failed"] + state["skipped"] + 1
        try:
            bundle = await scout(entity)
            update = await enrich(entity, bundle, deep=True)
            status = await asyncio.to_thread(apply_update, update)
            c = cost_of(update.usage)
            state["cost"] += c
            state["done"] += 1
            state["events"] += len(update.fields.get("events", []))
            state["services"] += len(update.fields.get("services", []))
            state["hours"] += len(update.fields.get("hours", []))
            ev = len(update.fields.get("events", []))
            print(f"[{i:>3}/{state['total']}] ✓ {entity['name'][:42]:<42} "
                  f"{status:<28} {('· '+str(ev)+' events') if ev else '':<11} ${state['cost']:.2f}")
        except Exception as e:
            await asyncio.to_thread(record_failure, entity["id"])
            state["failed"] += 1
            print(f"[{i:>3}/{state['total']}] ✗ {entity['name'][:42]:<42} {type(e).__name__}: {str(e)[:50]}")


async def run(args):
    targets = fetch_targets(args.limit, args.local_only, args.refresh)
    mode = "DRY-RUN (no writes)" if DRY_RUN else f"LIVE → {MODEL_DEEP}"
    est = len(targets) * 0.013
    print(f"\n=== Full enrichment run — {mode} ===")
    print(f"targets: {len(targets)}  |  est. cost ~${est:.2f}  |  "
          f"concurrency {args.concurrency}  |  cost cap ${args.cost_cap}\n")
    if not targets:
        print("Nothing to do — all eligible entities already enriched.")
        return

    state = {"total": len(targets), "done": 0, "failed": 0, "skipped": 0,
             "cost": 0.0, "events": 0, "services": 0, "hours": 0}
    sem = asyncio.Semaphore(args.concurrency)
    t0 = time.monotonic()
    await asyncio.gather(*(worker(e, sem, state, args.cost_cap) for e in targets))
    dt = time.monotonic() - t0

    print("\n" + "─" * 70)
    print(f"done: {state['done']}  failed: {state['failed']}  skipped(cap): {state['skipped']}")
    print(f"collected: {state['services']} services, {state['hours']} hours, {state['events']} events")
    print(f"cost: ${state['cost']:.2f}  |  time: {dt/60:.1f} min")
    if state["skipped"]:
        print(f"⚠ hit cost cap (${args.cost_cap}) — re-run to resume the remaining {state['skipped']}.")
    if DRY_RUN:
        print("DRY-RUN: re-run with DRY_RUN=0 to write for real.")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=0, help="max entities (0 = all eligible)")
    p.add_argument("--concurrency", type=int, default=6)
    p.add_argument("--cost-cap", type=float, default=25.0, help="USD; stop launching past this")
    p.add_argument("--local-only", action="store_true", help="Batavia-local entities only")
    p.add_argument("--refresh", action="store_true", help="re-enrich even if already done")
    asyncio.run(run(p.parse_args()))


if __name__ == "__main__":
    main()
