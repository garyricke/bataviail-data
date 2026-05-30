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
