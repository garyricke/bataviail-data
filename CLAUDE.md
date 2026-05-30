# BataviaIL Data Product — Project Context for Claude

## What This Is
A **data-first** community-data platform for Batavia, IL. The product is the
**data**: a Supabase Postgres source-of-truth, grown and kept fresh by an agent
swarm. The public site is a thin, read-only frontend over database views — built
**last**.

This is a separate project from the legacy webpage in `../bataviail-ai2026`
(a single self-contained `index.html`, presentation only, Cloudinary images).
Do not conflate them. Source-of-truth data lives **only** in Postgres here.

## Canonical plan
`plan/build-plan.md` is the **Path B** design (validated against Gemini + ChatGPT).
Read it before designing schema, scoping phases, or making architecture calls.
`plan/agent-data-pipeline.md` is the agent-swarm spec. `plan/goal.md` is the
original goal write-up (note: its "~1,100 FOIA businesses" was wrong — the actual
export is 5,455 rows → ~175 likely public-facing).

## Core principle: quarantine → promotion
Raw inputs (FOIA, scout discoveries, manual adds) land in **source-specific
tables** (`foia_records`, `entity_candidates`) and earn promotion into the
public-facing `entities` table via an **explicit, auditable step**. Nothing
writes directly to public data. Agents and the site both read/write through
Supabase only.

## Schema shape (Path B)
- **Identity & promotion:** `entities`, `locations`, `entity_location_links`, `foia_records`, `entity_candidates`, `candidate_matches`
- **Per-entity attributes:** `categories`, `entity_categories`, `entity_contacts`, `entity_social`, `entity_hours` (+ events/news/pricing/services later)
- `entities` has **no `address` column** — addresses live in `locations` (multi-tenant addresses are pervasive: e.g. 106 W Wilson St has 6 distinct entities).
- `entities.verification_status`: `unverified | scraped | claimed | verified`.
- Public reads go through views `entities_summary` (grid) and `entity_full` (modal). Anon key ships in the page; **RLS enforces read-only on those views**.

## Hard data numbers (from seed analysis — don't re-derive)
- Chamber: 521 entities (291 local, 230 regional = 44% regional dilution). 191 categories, 59 appear once. **All 521 lack hours.** 64 lack address, 381 lack logo, 129 lack contacts.
- FOIA: 5,455 rows → 907 unique PBO-address pairs → ~175 (19%) likely public-facing. 171 exact-match address overlaps with chamber.
- Realistic Phase 1 enrichment target: ~700 entities (521 chamber + ~175 promoted FOIA).

## Phased roadmap (Path B)
- **0a** (now): schema + chamber backfill + FOIA quarantine + verify data layer. No agent writes to production.
- **0b**: agent prototype on 5 pilots + FOIA classification + ~175 promotions.
- **1**: scale swarm to ~700 entities; tiered cadence; cheap-check vs deep-enrich.
- **2**: Auth + claim/edit + propose-override (moved up from Phase 4).
- **3**: ad bidding (Edge Functions + Stripe).
- **4**: persona personalization (pgvector, saved orgs).
- **5**: per-persona media (gated on traffic).
- **(later)**: build the public frontend over the views.

## Brand colors
- Navy `#292F7B` · Sky `#00ADEF` · Green `#60C560` · Gray `#7E7F81`

## Conventions
- Loaders are **idempotent** (re-runnable; upsert on natural keys like `memberId`).
- Secrets only in `.env` (gitignored). Service-role key never touches the frontend.
- Seed files in `data/seed/` are immutable inputs — never edited by code.
