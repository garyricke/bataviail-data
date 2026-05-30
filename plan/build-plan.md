# BataviaIL — Build Plan (Path B revision)

**Date:** 2026-04-30
**Working dir:** `/Users/garyricke/Documents/bataviail-ai2026/`
**Repo:** https://github.com/garyricke/bataviail (main branch)
**Status:** Revised after Gemini and ChatGPT evaluations. Major changes vs. prior draft are flagged inline as **[REVISED]**.

> A community portal for Batavia, IL that graduates from a single self-contained `index.html` into a Supabase-backed product with an autonomous agent swarm keeping a verified directory of Batavia organizations fresh — plus three monetization streams for local businesses.

---

## Table of Contents

1. [The Goal](#the-goal)
2. [Data Reality Check](#data-reality-check) **[NEW]**
3. [Approach](#approach)
4. [Architecture](#architecture)
5. [Database Schema](#database-schema)
6. [Phased Roadmap](#phased-roadmap)
7. [Phase 0a Punch List](#phase-0a-punch-list)
8. [Open Decisions](#open-decisions)
9. [Open Product Questions](#open-product-questions)

---

## The Goal

**Build the definitive, agent-fed map of every business and organization in Batavia — and turn it into something each persona, each owner, and each advertiser actually uses.**

Every business, school, club, church, park, and farmers-market stand in town belongs in **one master list**. Agents continuously research and write each entity's full profile — hours, events, contacts, products, reviews, photos, video. Visitors arrive, pick a persona, and get a tailored stream of events, orgs, and offers. Each entity gets a branded landing page that sounds like itself but lives inside a single, consistent Batavia voice. Owners can edit by chat, advertise across the site, or hire a local intern to capture deep-dive content on their behalf.

---

### 1. Build the master list

Three sources, **graduated into the master list through a verification pipeline** — not all dumped together. **[REVISED]**

| # | Source | Raw size | What it actually gives us |
|---|--------|---------|---------------------------|
| A | **Batavia Chamber of Commerce scrape** (`batavia_businesses_with_summaries.json`) | 521 entities (291 local, 230 regional) | Trusted launch seed. Every entity has a one-sentence agent-written summary. |
| B | **City inspections FOIA** (`InspectionsExport-combined.csv`) | **5,455 inspection rows → 907 unique PBO-address pairs → ~175 likely public-facing after triage** | Lead source, not a directory. Mostly inspection history with vacancies, common areas, and multi-tenant addresses. **[REVISED]** |
| C | **Manual + agent additions** | ∞ | Everything the chamber and FOIA don't cover (parks, schools, teams, clubs, churches, farmers market stands, boardwalk shops). |

**Critical change:** the FOIA file does **not** become entities by default. It lands in a `foia_records` quarantine table and is promoted into `entity_candidates` only after an LLM classification pass identifies likely-public-facing records. Candidates promote to `entities` only on dedupe + confidence checks. (See [Phase 0a](#phase-0a-punch-list) and [Database Schema](#database-schema).) **[REVISED]**

---

### 2. Agents build a full profile for every entity

A swarm of scouts researches each entity, then writes a structured profile — refreshed on a tiered cadence.

**Profile fields built per entity** (not all equally trustworthy — see [the freshness model](#freshness-and-verification)):

- **Location & hours** — high-churn, source-sensitive
- **Events** — high-churn; agents continuously sweep
- **Contacts & people** — medium-churn; PII-aware
- **Products, services, pricing** — medium-churn; volatile
- **About the business** — low-churn; written in their tone
- **Reviews** — read-only mirror with attribution; never republished raw at scale
- **High-quality images & videos** — best available, rights-aware
- **Categories & tags** — applied from a universal taxonomy and re-evaluated as the entity changes

**Tiered refresh cadence:**

| Tier | Cadence | Why |
|---|---|---|
| Pro orgs (4) | every 6h | They're paying for visibility |
| Platinum (9) | daily | Top chamber tier |
| Gold (53) | 3×/week | |
| Standard local (~225) | weekly | Long tail |
| Regional (230) | bi-weekly | Lowest priority |

Every change is logged to `entity_changelog` with a source.

#### Freshness and verification

**Refreshing facts is cheaper than re-enriching profiles.** Two cadences run in parallel: **[REVISED]**

- **Cheap freshness check** (most refreshes): pull the entity's homepage + one search result, diff against last-known structured fields, only call the LLM if a change is detected
- **Deep enrichment** (first-time onboarding, suspected drift, claim events): full scout bundle + Sonnet 4.6 enrichment

This separation is what keeps cost predictable as the directory scales.

---

### 3. Categorize every entity, define personas, map them dynamically

#### Categorization & tagging — universal

Define a category-and-tag taxonomy that fits every entity in the master list — from a barber shop to a Little League team to a riverfront park. **The current chamber taxonomy is a starting point, not the destination** (see [Data Reality Check](#data-reality-check)). **[REVISED]**

- Built from a curated list, applied to all confirmed entities
- Continuously updated as new entities and new event types appear
- Stored as structured fields so the persona-mapping system can query it directly
- Schema.org `LocalBusiness`/`Organization`/`CivicStructure` alignment is the long-term goal for portability

#### Personas & mapping — dynamic

A defined set of personas — different audiences with different reasons to interact with Batavia's businesses, events, and services.

- Each persona has interests, life stage, and seasonal needs
- Mapping is dynamic, not hard-coded — entities surface based on category, tag, season, and proximity
- **Cross-domain awareness:** a young family sees school events and team news alongside business events

**Current 7 synthesized personas:**

| ID | Name | Color | Audience |
|---|---|---|---|
| `family` | Family Explorer | green `#60C560` | Parents + kids |
| `teen` | Teen & Young Leader | sky `#00ADEF` | Ages 13–22 |
| `socialite` | Downtown Socialite | purple `#8b5cf6` | Ages 21–35 |
| `settler` | New-to-Batavia Settler | amber `#f59e0b` | New residents |
| `senior` | Senior & Care Circle | cyan `#06b6d4` | Ages 65+ |
| `business` | Small Business Builder | red `#ef4444` | Entrepreneurs |
| `volunteer` | Community Helper | emerald `#10b981` | Volunteers |

---

### 4. What visitors experience

A persona-first landing page → tailored discovery → individually branded entity pages — all in one consistent Batavia voice.

1. **Pick a persona on the landing page.** The visitor self-selects an audience. The dashboard reshapes around their interests, life stage, and current season.
2. **See events, products, and services that fit them right now.** Important upcoming events, in-season offerings, and cross-domain interests (school events, team news, community happenings) surface alongside business listings.
3. **Subscribe to a weekly Batavia newsletter and podcast.** **[REVISED]** Launch with **one universal Batavia Weekly** in both formats. Per-persona variants come online only when (a) audience size justifies the production cost and (b) entity event volume can support distinct streams. Don't ship 14 mediocre artifacts a week to chase a vision; ship one good one.
4. **Click through to an entity page.** **[REVISED]** Two tiers:
   - **Verified directory page** — every confirmed entity gets one. Consistent Batavia look and tone, structured fields, freshness badge.
   - **Branded long-scroll page** — reserved for **claimed entities, paying members, or intern-captured entities**. This is where the individual brand voice lives. Generating 1,600 distinct branded pages with no quality gate is not a goal; gating branded pages on ownership/claim is.

---

### 5. Three ways businesses invest in their presence

No CMS. No long contracts. Three clear price points that map to three clear outcomes. **All three depend on Auth being live, which is why Auth moves to Phase 2** (see [Phased Roadmap](#phased-roadmap)). **[REVISED]**

#### Stream 01 — Pay to edit your own listing

Small fee for an account. Owners log in and propose changes via chat — add photos, change hours, update services. Chat produces a **diff against current data**, the owner reviews and confirms via a structured approval screen, and the change is logged with provenance. **No content management system to learn — but also no unmediated writes to public data.** **[REVISED]**

#### Stream 02 — Pay to advertise

Bid for placements across the site, the persona dashboards, the weekly newsletter, and the weekly podcast. Highest active bid wins each slot. Inventory and slot definitions are deferred to Phase 3 — they require live traffic to set defensible pricing.

#### Stream 03 — Hire a local intern

Pay to have a Batavia intern audio- and video-interview the business, take photos, capture deep-dive content. Output flows back into the system and produces the entity's branded long-scroll page. **This is an operational program, not a software feature** — the MVP is "manual scheduling + simple intake form + content review queue," not an ops platform. **[REVISED]**

---

## Data Reality Check

**[NEW SECTION]** — Hard numbers surfaced by ChatGPT's analysis of the seed data. These shaped the Path B revisions.

### FOIA file is messier than the goal doc implied

| Metric | Value |
|---|---|
| Raw rows | 5,455 |
| Unique PBO-address pairs | 907 |
| Unique PBO names | 764 |
| Unique addresses | 799 |
| Duplicate-address groups | 756 covering 5,412 of 5,455 rows |
| Worst collisions | 1183 Pierson Dr (112 rows) · 1485 Louis Bork Dr (108) · 700 W Fabyan Pkwy (70) · 201 Houston St (70) |

**FOIA quality breakdown** (heuristic classification of 907 unique pairs):

| Class | Count | Share |
|---|---:|---:|
| Ambiguous / requires review | 426 | 47% |
| Likely public-facing | **175** | **19%** |
| Likely B2B / industrial / property | 141 | 16% |
| Vacant / closed | 79 | 9% |
| Residential / common area / apartments | 65 | 7% |
| Government / school / civic | 16 | 2% |
| Junk / missing / test | 5 | 1% |

**Implication:** the realistic Phase 1 enrichment target is **521 chamber + ~175 high-confidence FOIA = ~700 entities**, not "1,600." Cost ceilings should be calibrated to that number.

### Chamber data is a clean seed but not a launch directory

| Metric | Value |
|---|---|
| Total entities | 521 |
| Local Batavia | 291 (56%) |
| Regional | **230 (44%)** — Naperville, St. Charles, Aurora, etc. |
| Distinct categories | 191 |
| Categories appearing once | 59 |
| Top categories | Non-Profit (65), Restaurants & Taverns (36), Retailers (31), Residential Services (24), Contractors/Specialty (23) |
| Entities lacking address | 64 |
| Entities lacking logo URL | 381 |
| Entities lacking hours | **521 (all)** |
| Entities lacking contacts | 129 |
| Entities lacking social links | 57 |

**Taxonomy gaps for the manual-additions plan:**

| Manual addition target | Current chamber category coverage |
|---|---:|
| Schools | 11 |
| Churches / Ministries | 8 |
| Parks & Recreation | **2** |
| Boardwalk shops | **0** |
| Farmers Market stands | **0** |
| School teams / clubs | **0** (no taxonomy support) |

### The dedupe problem is real, not theoretical

- **171 exact address overlaps** between chamber and FOIA after normalization (1,467 FOIA rows ↔ 191 chamber entities)
- ~37% of chamber entities with addresses share an address with FOIA
- Address format mismatches between sources are pervasive: "1500 N. Raddant Road" (chamber) vs. "1500 N Raddant RD" (FOIA)
- Chamber itself has multi-tenant collisions: **106 W. Wilson St** appears across 6 distinct entities (chamber, law office, financial firm, two counseling practices, an aesthetics clinic)

**Implication:** the schema needs a `locations` table separate from `entities` and a `entity_location_links` join table. A single `address` column on `entities` is structurally wrong. **[REVISED]**

---

## Approach

**One foundation that supports every later phase without rework.**

Two principles update the original architecture after the evaluations: **[REVISED]**

1. **Source provenance is first-class.** Raw inputs (FOIA rows, chamber records, future scrapes) live in source-specific tables. They never write directly to public-facing `entities` rows. Promotion into `entities` is an explicit, auditable step.
2. **Auth is foundational, not Phase 4.** Owner claims, owner edits, ad bidding, saved orgs — every monetization-adjacent feature depends on identity. Auth moves to Phase 2. Phase 3 (ads) and Phase 4 (member personalization) build on it.

The four foundational moves:

1. **Replace the embedded data.** The 293-org `const ORGS` array becomes a Postgres table read through two public views: `entities_summary` (grid) and `entity_full` (modal).
2. **Keep the site static.** Frontend stays a single HTML page on Netlify. It just talks to Supabase via the JS client. Anon key ships in the page; RLS protects everything.
3. **Run an agent swarm against verified entities only.** **[REVISED]** Scouts feed Claude Haiku 4.5 enrichment for cheap freshness checks; Sonnet 4.6 for first-time onboarding and drift events. Writes go to `entity_candidates` first when applicable.
4. **Earn revenue at the right time.** Owner claim/edit comes online with Phase 2 Auth. Ad bidding (Phase 3) builds on it.

---

## Architecture

```
┌────────────────────────────────────────────────────────────┐
│  index.html (Netlify, static)                              │
│   • Supabase JS client (CDN)                               │
│   • Page load: select from public.entities_summary view    │
│   • Modal open: select from public.entity_full view        │
│   • Phase 2+: signed-in owner edit, claim flow             │
└────────────┬───────────────────────────────────────────────┘
             │ anon key, RLS read-only on public views
             ▼
┌────────────────────────────────────────────────────────────┐
│  Supabase project (free tier)                              │
│   ├── Postgres                                             │
│   │     • entities, locations, entity_location_links       │
│   │     • foia_records, entity_candidates, candidate_matches│
│   │     • contacts, events, news, hours, …                 │
│   │     • profiles, saved_orgs (Phase 4)                   │
│   │     • ad_slots, ad_bids, ad_impressions (Phase 3)      │
│   ├── Auth (email, OAuth)        ← Phase 2 [REVISED]       │
│   ├── Storage (S3-compat)        ← owner uploads, intern   │
│   ├── Edge Functions (Deno)      ← ad auction, Stripe hook │
│   └── pg_cron                    ← nightly maintenance     │
└────────────▲───────────────────────────────────────────────┘
             │ service role key (server-side only, in GH Actions secrets)
             │
┌────────────┴───────────────────────────────────────────────┐
│  Agent swarm (Python, runs on GitHub Actions cron)         │
│   ┌─ orchestrator.py                                       │
│   │   1. SELECT entity_id WHERE next_due_at <= now()       │
│   │   2. Cheap freshness check first; LLM only on diff     │
│   │   3. asyncio.gather() scouts per entity, capped        │
│   │   4. Write to entity_candidates (new) or entities      │
│   │      (verified); always append entity_changelog        │
│   │   5. UPDATE entity_freshness.next_due_at               │
│   └─ scouts: website, news, search API, official feeds     │
│      (FB/IG/Yelp scraping deferred — see Open Decisions)   │
└────────────────────────────────────────────────────────────┘
```

**The load-bearing decision:** the site and the swarm communicate only through the database. Every later capability — ad bids, membership, claim-your-listing — is a new table plus a small function, not a redesign.

**RLS policy intent:**
- `anon` role: SELECT on `entities_summary`, `entity_full`, `entity_events`, `entity_news`. Nothing else. No writes.
- `authenticated` role (Phase 2): writes to `profiles`, `saved_orgs`, `entity_overrides_proposed` (own claims only).
- `service_role` (agent): full access. Key lives only in GitHub Actions secrets.

---

## Database Schema

### Identity, sources, and candidates **[NEW SECTION]**

```sql
-- Raw FOIA records, never directly exposed
create table foia_records (
  id bigserial primary key,
  pbo_name text not null,
  raw_address text not null,
  normalized_address text,
  inspection_date timestamptz,
  raw jsonb,                          -- full original row
  classification text,                -- public_facing | b2b | vacant | residential | civic | junk | ambiguous
  classified_at timestamptz,
  promoted_to_candidate_id bigint     -- → entity_candidates.id when promoted
);

-- Holding pen for not-yet-trusted entities (FOIA, manual additions, scout discoveries)
create table entity_candidates (
  id bigserial primary key,
  source text not null,               -- foia | manual | scout
  source_record_id bigint,            -- → foia_records.id when applicable
  proposed_name text,
  proposed_address text,
  proposed_phone text,
  proposed_website text,
  confidence numeric,                 -- 0–1 derived score
  status text default 'needs_review', -- needs_review | matched | promoted | rejected
  matched_entity_id text,             -- if matched to an existing entities row
  notes text,
  created_at timestamptz default now(),
  reviewed_at timestamptz, reviewed_by text
);

-- Match attempts between candidates and existing entities
create table candidate_matches (
  id bigserial primary key,
  candidate_id bigint references entity_candidates on delete cascade,
  entity_id text references entities on delete cascade,
  match_type text,                    -- exact_address | normalized_address | name_similarity | manual
  similarity numeric,
  decision text,                      -- accept | reject | pending
  decided_at timestamptz, decided_by text
);
```

### Entity, location, and the multi-tenant model **[REVISED]**

```sql
-- Core entity record (slowly changing)
create table entities (
  id text primary key,                -- chamber memberId or generated id
  name text not null,
  slug text unique not null,
  is_local boolean not null default true,
  membership_level text,              -- Standard | Gold | Platinum | Pro
  phone text, website text,
  description text, summary text,
  logo_url text, banner_url text,
  source text default 'chamber',      -- chamber | foia | manual | claimed
  verification_status text default 'unverified', -- unverified | scraped | claimed | verified
  last_verified_by text,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

-- Physical locations live separately so multi-tenant addresses model correctly
create table locations (
  id bigserial primary key,
  raw_address text not null,
  normalized_address text not null,
  street_number text, street_name text, suite text,
  city text, state text, zip text,
  lat numeric, lng numeric,
  is_multi_tenant boolean default false,
  created_at timestamptz default now()
);
create unique index on locations(normalized_address, coalesce(suite, ''));

create table entity_location_links (
  entity_id text references entities on delete cascade,
  location_id bigint references locations on delete cascade,
  role text default 'primary',        -- primary | branch | mailing | parent_building
  active_from date, active_to date,
  primary key (entity_id, location_id, role)
);
```

### Per-entity attribute tables (largely unchanged from prior draft)

```sql
create table categories (id serial primary key, name text unique not null);
create table entity_categories (
  entity_id text references entities on delete cascade,
  category_id int references categories on delete cascade,
  primary key (entity_id, category_id)
);

create table entity_contacts (
  id bigserial primary key,
  entity_id text references entities on delete cascade,
  name text, title text, phone text, email text,
  verified_at timestamptz, source text
);

create table entity_social (
  entity_id text primary key references entities on delete cascade,
  facebook text, instagram text, linkedin text,
  youtube text, twitter text, tiktok text
);

create table entity_hours (
  entity_id text primary key references entities on delete cascade,
  structured jsonb, freeform text, last_seen_at timestamptz
);

create table entity_events (
  id bigserial primary key,
  entity_id text references entities on delete cascade,
  title text not null, starts_at timestamptz, ends_at timestamptz,
  url text, source text, scraped_at timestamptz default now(),
  unique (entity_id, title, starts_at)
);

create table entity_news (
  id bigserial primary key,
  entity_id text references entities on delete cascade,
  headline text not null, url text not null, published_at timestamptz,
  source text, scraped_at timestamptz default now(),
  unique (entity_id, url)
);

create table entity_pricing (
  entity_id text primary key references entities on delete cascade,
  tier text, price_range text, items jsonb,
  last_seen_at timestamptz, sources jsonb
);

create table entity_services (
  entity_id text references entities on delete cascade,
  service text,
  primary key (entity_id, service)
);
```

### Owner edits proposed (Phase 2) **[REVISED]**

```sql
-- Owner-proposed edits land here first, then promote to entity_overrides on approval
create table entity_overrides_proposed (
  id bigserial primary key,
  entity_id text references entities on delete cascade,
  proposed_by uuid references auth.users on delete set null,
  field_path text not null,
  current_value jsonb, proposed_value jsonb,
  chat_transcript jsonb,
  status text default 'pending',      -- pending | approved | rejected
  reviewed_at timestamptz, reviewed_by text,
  created_at timestamptz default now()
);

create table entity_overrides (
  id bigserial primary key,
  entity_id text references entities on delete cascade,
  field_path text not null,
  value jsonb not null,
  submitted_by text, verified_by text,
  expires_at timestamptz,             -- overrides aren't permanent
  created_at timestamptz default now()
);
```

### Agent operations and freshness

```sql
create table entity_freshness (
  entity_id text primary key references entities on delete cascade,
  tier text not null,
  last_refreshed_at timestamptz,
  last_deep_enriched_at timestamptz,  -- distinguish cheap check vs deep
  next_due_at timestamptz,
  last_status text,
  failure_streak int default 0
);

create table entity_changelog (
  id bigserial primary key,
  entity_id text references entities on delete cascade,
  changed_at timestamptz default now(),
  field_path text, old_value jsonb, new_value jsonb,
  source text                          -- agent | override | claim | promotion
);

create table scout_cache (
  url text primary key,
  etag text, last_modified text,
  body bytea, content_type text,
  fetched_at timestamptz default now()
);

create table agent_runs (
  id bigserial primary key,
  started_at timestamptz default now(), finished_at timestamptz,
  scope jsonb, cost_usd numeric(10,4), status text, error text
);
```

### Public read views

```sql
create view entities_summary as
  select e.id, e.name, e.slug, e.is_local, e.membership_level,
         e.verification_status,
         coalesce(loc.city, '') as city,
         e.logo_url, e.summary,
         array_agg(c.name) filter (where c.name is not null) as categories,
         f.last_refreshed_at
  from entities e
  left join entity_categories ec on ec.entity_id = e.id
  left join categories c on c.id = ec.category_id
  left join entity_freshness f on f.entity_id = e.id
  left join lateral (
    select l.city from entity_location_links ell
    join locations l on l.id = ell.location_id
    where ell.entity_id = e.id and ell.role = 'primary'
    limit 1
  ) loc on true
  group by e.id, f.last_refreshed_at, loc.city;

-- entity_full view: joins per-entity attribute tables for the modal
```

---

## Phased Roadmap

**[REVISED — Phase 0 split, Auth moved to Phase 2]**

| Phase | Timeline | What |
|---|---|---|
| **0a** | Day 1–2 (8–12 hrs) | Supabase schema (incl. `locations`, `foia_records`, `entity_candidates`) + chamber backfill + read-only frontend |
| **0b** | Week 1 | Agent prototype against 5 chamber pilots + FOIA classification pass |
| **1** | Week 2–3 | Scale agent swarm to all 521 chamber + ~175 promoted FOIA candidates; tiered cadence; freshness signal on cards |
| **2** | Week 4–5 | **Auth + claim/edit + propose-override flow** [moved up] |
| **3** | Later | Ad bidding (Edge Functions + Stripe) — depends on Phase 2 Auth |
| **4** | Later | Membership personalization — pgvector matching, saved orgs, persona overrides |
| **5** | Later | Per-persona newsletter/podcast variants (after Phase 1 traffic justifies); branded long-scroll pages for claimed/intern-captured entities only |

### Phase 0a — schema + chamber backfill + frontend (8–12 hrs)

The deliberate scope reduction. **No agent writes hit production in this phase.** **[REVISED]**

- **0a.1 — Spin up Supabase project (~30 min).** Free tier, region `us-east-2`. Save URL + anon key + service role key locally; commit none of them.
- **0a.2 — Run schema SQL (~1 hr).** Includes the new `locations`, `foia_records`, `entity_candidates`, `candidate_matches` tables.
- **0a.3 — Backfill chamber data (~2 hrs).** `scripts/backfill_from_chamber_json.py` — UPSERTs into `entities`, `locations`, `entity_location_links`, `categories`, `entity_categories`, `entity_contacts`, `entity_social`. Seeds `entity_freshness` with tier + `next_due_at = now()`. Verify: 521 entities, ~191 categories, ~600 contacts, locations deduplicated for shared addresses.
- **0a.4 — Load FOIA into quarantine (~1 hr).** `scripts/load_foia_quarantine.py` — INSERT all 5,455 rows into `foia_records` with `classification = null`. Nothing promoted yet.
- **0a.5 — Rewrite the site to read from Supabase (~3 hrs).** Replace `const ORGS` with Supabase JS client calls to `entities_summary` and `entity_full`. Anon key ships in the page; RLS protects.
- **0a.6 — End-to-end verification (~30 min).** Dashboard renders all 521 chamber entities; modal still works for chamber data; nothing FOIA-derived shows.

**End of Phase 0a:** the live site is reading from Supabase. Chamber data is fully loaded with proper location modeling. FOIA is quarantined. No agents have written to production yet.

### Phase 0b — agent prototype + FOIA triage (Week 1)

- **0b.1 — FOIA classification pass.** Single LLM call per unique PBO-address pair → assign `classification` in `foia_records`. Manual spot-check on 50 random rows.
- **0b.2 — Promote high-confidence FOIA → candidates.** `classification IN ('public_facing')` and exact-address match against existing `entities` → auto-match candidate; everything else → `needs_review`.
- **0b.3 — Build minimal `agents/orchestrator.py` + 2 scouts** (website + Brave Search) and run against 5 chamber pilots: Chuck's Cheeseburgers, 63rd Street Apothecary, A Step Above Dance Academy, 1833 Leadership Academy, Water Street Studios.
- **0b.4 — Dry-run mode first.** Print diffs without writing for the first 24 hours of runs. Manual approval required to flip on writes.
- **0b.5 — Wire GitHub Actions cron**, manual-trigger only at first.

**End of Phase 0b:** 5 chamber entities deeply enriched. ~175 FOIA candidates exist (none yet promoted to `entities`). Manual-trigger agent runner exists.

### Phase 1 — scale the swarm (Week 2–3)

- Roll enrichment to all 521 chamber + promoted FOIA entities (~700 total target)
- Tiered refresh cadence (table above)
- Cheap freshness check vs. deep enrichment split (see [Freshness and verification](#freshness-and-verification))
- Surface `last_refreshed_at` as "Updated 2d ago" badges on org cards
- Cost cap per run ($5); `failure_streak >= 3` auto-pauses an entity
- **Defer FB/IG/Yelp scraping.** Use official feeds, allowed RSS, and search APIs. Social scraping returns only when (a) it's via Graph API for authorized pages, or (b) the cost of failure is low.

### Phase 2 — Auth + claim/edit (Week 4–5) **[MOVED UP]**

- Supabase Auth: magic link + Google OAuth
- `/claim/<entity-id>` page: email-domain or phone verification flow
- Owner edit experience: chat → diff → review screen → write to `entity_overrides_proposed`
- Approval queue (initially: solo-dev review; later: trust-graduated owners can self-approve)
- `entity_overrides` win in `entity_full` view

### Phase 3 — Ad bidding (later)

Builds on Phase 2 Auth. Tables: `ad_slots`, `ad_bids`, `ad_impressions`, `advertisers`. Edge Function `select-ad-for-slot(slot_id)`. Stripe Checkout for one-time slot purchases. Slot inventory and pricing decided after Phase 1 traffic data exists.

### Phase 4 — Membership personalization (later)

`profiles` (with `interests`, `household`, `radius_miles`, `embedding`), `saved_orgs`. pgvector cosine matching for signed-in users. Free tier still works without an account.

### Phase 5 — Media and branded pages (later)

- **One** universal Batavia Weekly newsletter and podcast at first
- Per-persona variants only after engagement metrics justify
- Branded long-scroll pages reserved for claimed entities, paying members, or intern-captured entities — never auto-generated at scale
- Audio pipeline: TTS provider + audio hosting + RSS feed generation; not free-tier-friendly (budget separately)

---

## Phase 0a Punch List

In order. Don't move on until the previous step is verified.

1. **Spin up Supabase project + run schema SQL** (incl. `locations`, `foia_records`, `entity_candidates`) — ~90 min
2. **Backfill 521 chamber entities** with proper location modeling — ~2 hrs
3. **Load FOIA into `foia_records` quarantine** — ~1 hr
4. **Rewrite `index.html` data layer** to use Supabase JS client (`entities_summary` + `entity_full`) — ~3 hrs
5. **Verify end-to-end:** 521 chamber rows in dashboard, modal works for chamber data, FOIA invisible to public views — ~30 min

**Total: 8–12 hrs.** Realistic for a focused solo-dev day or two. Doesn't include agent code, FOIA classification, or Auth — those are Phase 0b and Phase 2.

---

## Open Decisions

None of these block Phase 0a. But they need answers before Phase 0b → Phase 1.

1. **Search API** — Brave Search ($3/1k) vs. SerpAPI ($75/mo) vs. SearXNG. *Recommend Brave to start.*
2. **FOIA promotion threshold.** What confidence + signal combination auto-promotes a candidate to `entities`? Initial proposal: `classification = public_facing` AND (exact-address match to chamber OR independent-website-found). Everything else → human review queue.
3. **Multi-tenant policy.** When 6 entities share an address (e.g., 106 W. Wilson St), what does the location modal show? Show the building (parent location with tenants listed) or always the entity (with the building referenced)?
4. **Storage choice.** Cloudinary stays for current images. Use Supabase Storage only for owner-uploaded content (claim flow, ad creatives, intern uploads).
5. **Where the agent cron runs.** GitHub Actions (free, 6h max) vs. pg_cron + Edge Functions vs. a $5 Hetzner box. *Recommend GitHub Actions until we outgrow it.*
6. **Anon key exposure.** Safe in the static page *if* RLS is correct on every table from day one. RLS audit before going live.
7. **TTS provider for media phase.** Defer until Phase 5; budget separately ($40–85/mo at one universal weekly podcast, more if persona variants come online).

---

## Open Product Questions

These came out of the goal definition and the evaluations. Worth keeping live as the plan progresses.

1. **Persona model: flat or composable?** The 7 current personas were synthesized from research, but cross-domain interest (a "young family" getting school events alongside business events) suggests personas should be composable along (life stage × interests × household). Refactor when Phase 4 personalization comes online.
2. **Universal taxonomy for heterogeneous entity types.** A barber shop, a Little League team, a riverfront park, a church, and a farmers-market stand need to live in the same taxonomy. Schema.org alignment looks viable but requires a custom extension for school-club / team / market-stand types. Stand up a v1 taxonomy in Phase 1 and revise.
3. **Per-persona podcast/newsletter — when is the threshold met?** Define audience-size and event-volume thresholds *before* launching variants, not after.
4. **Entity-page generation vs. curation.** Are entity pages templated and field-driven, or LLM-generated and edited? The two approaches have very different quality gates and update costs. Phase 1 is templated; branded long-scroll (Phase 5+) is hybrid.
5. **Intern program operations.** Recruiting (BHS, Aurora U, Waubonsee?), liability/insurance, equipment loans, content review, scheduling. Build a one-page operating doc before pitching it to the first paying business.
6. **Owner edits via chat — verification model.** What proves an edit is from the legitimate owner? Email-domain match? Phone verification? Notarized claim? Risk increases with the value of the field being edited (logo < hours < contact info < ownership).
7. **Ad inventory & pricing.** Persona-targeted slots in podcasts and newsletters need defined inventory, floor prices, and creative format constraints. Punted to Phase 3 — needs traffic data first.
8. **Review attribution & rights.** Mirroring Google/Yelp reviews at scale carries TOS risk. Show counts + links + most-recent-snippet only? Or pursue Google Places API for licensed access?

---

## Brand Reference

- **Navy:** `#292F7B`
- **Sky Blue:** `#00ADEF`
- **Green:** `#60C560`
- **Gray:** `#7E7F81`

## File Reference

- `index.html` — main landing page (~348KB, all images on Cloudinary)
- `CLAUDE.md` — full project context
- `batavia_businesses_with_summaries.json` — 291 local + 230 regional orgs
- `plan/BataviaIL.ai-goal-30apr2026.md` — original goal write-up
- `plan/agent-data-pipeline.md` — earlier technical spec (superseded by this Path B revision in part)
- `plan/foia-request-bus/InspectionsExport-combined.csv` — 5,455 inspection records
- `plan/build-plan.html` — visual version of this plan (pending update to match Path B)
- `plan/build-plan.md` — *this file*
