# Agent swarm (Phase 0b+)

Built **after** the data layer is verified (README steps 1–5). Spec lives in
[`../plan/agent-data-pipeline.md`](../plan/agent-data-pipeline.md) and the agent
section of [`../plan/build-plan.md`](../plan/build-plan.md).

Design summary (Path B):
- Orchestrator reads `entity_freshness.next_due_at`, forks scouts in parallel.
- **Cheap freshness check first** (diff homepage + one search result); only call an LLM on detected change.
- **Deep enrichment** (onboarding, drift, claim events) uses Sonnet 4.6; routine refreshes use Haiku 4.5 + prompt caching.
- Scouts cache raw responses in `scout_cache` by URL+etag.
- Tiered cadence: Pro 6h · Platinum daily · Gold 3×/wk · Standard weekly · Regional bi-weekly.
- Cost cap ~$6–12/day at ~700 entities. `failure_streak >= 3` auto-pauses an entity.

**Phase 0b first milestone:** prototype against 5 chamber pilots + classify FOIA
quarantine + promote ~175 candidates. Pilots: Chuck's Cheeseburgers, 63rd Street
Apothecary (20744), A Step Above Dance Academy (18746), 1833 Leadership Academy
(20831), Water Street Studios.

## Prototype scaffold (runnable now, dry-run)

| Module | Role |
|---|---|
| `config.py` | mode + models + pilots + thresholds. **DRY_RUN is ON by default**; opt out with `DRY_RUN=0`. |
| `db.py` | entity reads; `apply_update()` is a no-op in dry-run (write guard) |
| `scout.py` | gather raw signals → `ScoutBundle`. Dry-run synthesizes deterministically; `_scout_live` = Brave + homepage fetch later |
| `enrich.py` | `ScoutBundle` → reviewable `ProposedUpdate`. Dry-run structures without an LLM; live uses Sonnet (deep) / Haiku (routine) |
| `orchestrator.py` | loads pilots, scouts+enriches concurrently (asyncio), reports proposed writes, routes non-chamber pilots to manual onboarding |
| `classify_foia.py` | classifies the 799 distinct quarantine addresses; dry-run heuristic = chamber-overlap → public_facing |

Run (dry-run, no keys/cost, no writes):

```bash
.venv/bin/python -m agents.orchestrator
.venv/bin/python -m agents.classify_foia
```

Dry-run results against live data: 4 pilots propose hours/social/news, Chuck's →
manual onboarding; FOIA classifier auto-finds **148** public-facing via chamber
overlap, leaving **651** for the real LLM+web pass (the path to ~175).

**To go live (later):** fill `ANTHROPIC_API_KEY` + `BRAVE_API_KEY` in `.env`,
implement `_scout_live` / `_enrich_live` / the LLM classifier + `apply_update`
write path, then run with `DRY_RUN=0`.
