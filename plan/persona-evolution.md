# Persona matching — evolution plan

How the directory's "view by persona" feature evolves from simple category rules
(now) to AI vector + behavior personalization (Phase 4), **without a rebuild at
each step**. Aligns with CLAUDE.md Phase 4 (pgvector + saved orgs).

## The core principle: relevance is a SCORE, not a filter
Even in Stage 1, every (persona, org) pair gets a numeric relevance score. The UI
always consumes a *ranked list*. Each later stage only **adds terms to the same
score** — the frontend never changes as the brains behind it get smarter.

```
score(persona, org) =
    w1 * category_match        # Stage 1  (rules)
  + w2 * semantic_similarity   # Stage 3  (pgvector, content)
  + w3 * engagement_prior      # Stage 4  (behavior, needs real users)
  + w4 * tier_boost            # business model (Pro / sponsored)
```

Two supporting decisions, made now:
- **Persona definitions live in data** — `web/personas.js` today (key, label,
  tagline, color, category bundle); a `personas` table later. Not hardcoded in
  page markup.
- **Matching lives behind a seam** — one function, `rankForPersona(key, orgs)`.
  Today its insides are a client-side category score; later it becomes a Supabase
  RPC (`persona_orgs(key)`) doing pgvector + behavior. Callers don't change.

## Stages

### Stage 1 — Category rules (NOW)
Persona → bundle of the `categories` already on entities → score = count of an
org's categories that fall in the bundle. Deterministic, explainable, zero ML
infra. Config in `web/personas.js`; scoring in `rankForPersona()`.

### Stage 2 — Instrument engagement (the moment real people arrive)
The single most important enabler of AI matching, and cheap to add now: log
`persona_selected`, `org_clicked`, `org_opened`, outbound clicks, saves into an
`interaction_log` table (anon INSERT-only via RLS). **Start collecting from day
one** while Stage 1 is live, so a usable corpus exists by the time we want it.
Without this behavioral signal, "AI matching" is just unsupervised guessing.

### Stage 3 — Content embeddings (can start offline, no users needed)
Embed each org (summary + services + categories) and each persona intent; store
vectors in a `pgvector` column (`entity_embeddings`). Ranking gains **semantic
similarity**, catching good matches the category bundles miss. Pure content
upgrade — buildable in parallel before traffic exists.

### Stage 4 — Hybrid ranking (once Stage 2 + 3 exist)
Blend the score terms above; tune weights against Stage-2 engagement data. Keep
category rules as a guardrail + explainability layer ("shown because: Schools,
Recreation"). Swap `rankForPersona()`'s insides to call the RPC.

### Stage 5 — Per-person personalization (Phase 4 proper)
With auth + saved orgs, a persona becomes the **cold-start prior** and an
individual's own behavior vector refines it (a "family" user who keeps opening
breweries gets a blended feed). Personas become starting points, not buckets.

## What real users specifically unlock
1. **Supervision** — engagement says which matches are actually good (tune, don't guess).
2. **Validation** — which personas get used, whether the category bundles feel right (A/B the mappings).
3. **Justification** — proves the ML infra is worth building before we build it.

## Migration checklist (so we never paint into a corner)
- [x] Score-based ranking from day one (`rankForPersona`).
- [x] Persona config as data (`web/personas.js`).
- [ ] `interaction_log` table + client `logInteraction()` wired on day one (Stage 2 hook).
- [ ] Move `rankForPersona` behind a Supabase RPC seam when DB-side matching lands.
- [ ] `entity_embeddings` (pgvector) generated offline (Stage 3).
- [ ] Hybrid scoring weights tuned on engagement data (Stage 4).
