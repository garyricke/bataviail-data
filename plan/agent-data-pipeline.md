# Agent-Driven Data Pipeline + Auto-Updating Site (v2 — Supabase-backed)

## Goal
Build a real backend now (Supabase + Postgres) so the agent swarm, membership system, and ad-bidding system all share one foundation. Replace the embedded `const ORGS` array with live DB reads. Site stays a static HTML frontend on Netlify; everything dynamic happens through Supabase.

## Why this revision
v1 of this plan stored enriched entity data as JSON files in git, refreshed by a cron job. That works for ~10 days then breaks: hundreds of commits/day, merge conflicts between parallel scouts, no way to host PII (membership) or financial state (ad bids), no real query layer. Phase 3 was going to force a DB anyway — building twice is wasted work. Supabase gives us auth, Postgres, edge functions, realtime, pgvector, and storage in one free tier. We adopt it as the base architecture from day one.

---

## The architecture in one diagram

```
┌────────────────────────────────────────────────────────────┐
│  index.html (Netlify, static)                              │
│   • Supabase JS client (CDN)                               │
│   • Page load: select from public.entities_summary view    │
│   • Modal open: select from public.entity_full view        │
│   • Future: signed-in user → personalized matching         │
└────────────┬───────────────────────────────────────────────┘
             │ anon key, RLS read-only on public views
             ▼
┌────────────────────────────────────────────────────────────┐
│  Supabase project (free tier)                              │
│   ├── Postgres                                             │
│   │     • entities, contacts, events, news, hours, …       │
│   │     • profiles, saved_orgs (Phase 4)                   │
│   │     • ad_slots, ad_bids, ad_impressions (Phase 3)      │
│   ├── Auth (email, OAuth)        ← Phase 4                 │
│   ├── Storage (S3-compat)        ← optional, replaces some │
│   │                                Cloudinary use          │
│   ├── Edge Functions (Deno)      ← ad auction, Stripe hook │
│   └── pg_cron                    ← nightly maintenance     │
└────────────▲───────────────────────────────────────────────┘
             │ service role key (server-side only, in GH Action secrets)
             │
┌────────────┴───────────────────────────────────────────────┐
│  Agent swarm (Python, runs on GitHub Actions cron)         │
│   ┌─ orchestrator.py                                       │
│   │   1. SELECT entity_id WHERE next_due_at <= now()       │
│   │   2. asyncio.gather() scouts per entity, capped        │
│   │   3. enrich via Claude API (Haiku 4.5 + prompt cache)  │
│   │   4. UPSERT entity tables, append entity_changelog     │
│   │   5. UPDATE entity_freshness.next_due_at               │
│   └─ scouts: website, facebook, instagram, google, news,   │
│       yelp — each cached by URL+etag in scout_cache table  │
└────────────────────────────────────────────────────────────┘
```

The agent swarm and the site never touch each other directly. Both go through the database. That's the property that makes everything else possible.

---

## Database schema (Phase 0–1 tables)

```sql
-- Core entity record (slowly changing)
create table entities (
  id text primary key,                      -- chamber memberId, e.g. '20831'
  name text not null,
  slug text unique not null,                -- url-safe
  is_local boolean not null default true,   -- vs. regional
  membership_level text,                    -- Standard | Gold | Platinum | Pro
  address text, city text, state text, zip text,
  phone text, website text,
  description text, summary text,
  logo_url text, banner_url text,
  source text default 'chamber',            -- chamber | foia | manual | claimed
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create table categories (
  id serial primary key,
  name text unique not null
);

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
  structured jsonb,            -- {mon:{open,close}, ...}
  freeform text,
  last_seen_at timestamptz
);

-- High-churn agent-populated tables
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
  tier text,                   -- $ | $$ | $$$
  price_range text,
  items jsonb,                 -- [{name, price, unit}]
  last_seen_at timestamptz, sources jsonb
);

create table entity_services (
  entity_id text references entities on delete cascade,
  service text,
  primary key (entity_id, service)
);

-- Owner-submitted overrides (win over agent data)
create table entity_overrides (
  id bigserial primary key,
  entity_id text references entities on delete cascade,
  field_path text not null,    -- e.g. 'hours.structured.mon'
  value jsonb not null,
  submitted_by text, verified_by text,
  created_at timestamptz default now()
);

-- Agent operational tables
create table entity_freshness (
  entity_id text primary key references entities on delete cascade,
  tier text not null,          -- pro | platinum | gold | standard | regional
  last_refreshed_at timestamptz,
  next_due_at timestamptz,
  last_status text,            -- ok | http_error | parse_error | blocked
  failure_streak int default 0
);

create table entity_changelog (
  id bigserial primary key,
  entity_id text references entities on delete cascade,
  changed_at timestamptz default now(),
  field_path text, old_value jsonb, new_value jsonb,
  source text                  -- agent | override | claim
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
  scope jsonb,                 -- which entities, which scouts
  cost_usd numeric(10,4), status text, error text
);

-- Public read views (RLS exposes these, not the base tables)
create view entities_summary as
  select e.id, e.name, e.slug, e.is_local, e.membership_level,
         e.city, e.logo_url, e.summary,
         array_agg(c.name) filter (where c.name is not null) as categories,
         f.last_refreshed_at
  from entities e
  left join entity_categories ec on ec.entity_id = e.id
  left join categories c on c.id = ec.category_id
  left join entity_freshness f on f.entity_id = e.id
  group by e.id, f.last_refreshed_at;

-- entity_full view: same idea, joins all the per-entity tables for the modal
```

**RLS policy intent:**
- `anon` role: SELECT on `entities_summary`, `entity_full`, `entity_events`, `entity_news`. Nothing else. No writes.
- `authenticated` role (Phase 4): adds writes to `profiles`, `saved_orgs` (own rows only).
- `service_role` (agent): full access. Key lives only in GH Actions secrets.

---

## Phase 0 — Today (6–10 hrs): Stand up the foundation

### 0.1 — Create the Supabase project (~30 min)
- New project, free tier, region `us-east-2` (closest to typical Batavia visitors).
- Save URL + anon key + service role key locally; commit none of them.
- Run the schema SQL above through the SQL editor.

### 0.2 — Backfill from existing JSON (~1 hr)
- Write `scripts/backfill_from_chamber_json.py` (one-shot): reads `batavia_businesses_with_summaries.json`, UPSERTs into `entities`, `entity_categories`, `entity_contacts`, `entity_social`, plus seeds `entity_freshness` with tier + `next_due_at = now()`.
- Verify row counts: 521 entities, ~70 categories, ~600 contacts.

### 0.3 — Pick 5 test entities and enrich them end-to-end (~2 hrs)
Same five as before — Chuck's, 63rd Street Apothecary, A Step Above Dance, 1833 Leadership, Water Street Studios.
- Run a stripped-down `agents/orchestrator.py --only 20831,20744,18746,...` against just these.
- Confirm `entity_events`, `entity_news`, `entity_pricing`, `entity_services`, `entity_changelog` all populate.

### 0.4 — Rewrite the site to read from Supabase (~2 hrs)
Replace lines around `index.html:308` (the `const ORGS` literal) with:
```html
<script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2"></script>
<script>
  const sb = supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);
  let ORGS = [];
  async function loadOrgs() {
    const { data, error } = await sb.from('entities_summary').select('*');
    if (error) { console.error(error); return; }
    ORGS = data;
  }
  async function loadOrgDetail(id) {
    const { data } = await sb.from('entity_full').select('*').eq('id', id).single();
    return data;
  }
</script>
```
Modal-open handler calls `loadOrgDetail(id)` instead of reading from the embedded array. SUPABASE_URL and the anon key are public — they're meant to ship in the page; RLS protects the data.

### 0.5 — Wire the agent runner (~1–2 hrs)
- `agents/orchestrator.py` runs locally first, manual-only, against the 5 test entities. Reads `SUPABASE_SERVICE_ROLE_KEY` from `.env`.
- Dry-run mode prints diffs without writing.
- Once trusted, add `.github/workflows/refresh-data.yml` with `cron: '0 7 * * *'`. Service role key goes in GH Actions secrets.

**End of day 1: Supabase has all 521 entities; 5 are deeply enriched; the live site reads from the DB; the agent has a manual-trigger button you can press to refresh.**

---

## Phase 1 — Week 1: Scale the swarm

### Scout pattern
Each scout is a coroutine that:
1. Looks up the URL in `scout_cache`. If `etag`/`last_modified` present, sends conditional GET.
2. On 304, returns cached body. On 200, updates cache.
3. Returns `{url, status, body, parsed_summary}` to orchestrator.

### Enrichment pattern
One Claude API call per entity, structured tool use forcing `entity.schema.json` shape. Aggressive prompt caching: schema + few-shot examples are the cache prefix; only the scout bundle varies. Cuts cost ~10×.

Use **Claude Haiku 4.5** for routine refreshes; **Sonnet 4.6** for first-time onboarding or messy scout output (orchestrator picks based on failure_streak / age).

### Cost ceiling (back-of-envelope)
- 521 entities × 1 enrichment/day × ~3K input + 1K output on Haiku ≈ **$2–4/day** with caching
- Tiered cadence cuts further:

| Tier | Cadence | Why |
|---|---|---|
| Pro orgs (4) | 6h | They're paying for visibility |
| Platinum (9) | daily | Top chamber tier |
| Gold (53) | 3×/week | |
| Standard local (229) | weekly | Long tail |
| Regional (230) | bi-weekly | Lowest priority |

### Politeness / safety
- `agents/config.yaml` allowlist of source domains + per-domain rate cap (e.g. 1 req / 3s).
- Respect `robots.txt` (`urllib.robotparser`).
- Hard cost cap per run (e.g. $5) — orchestrator aborts if exceeded.
- `failure_streak >= 3` auto-pauses an entity until manually cleared.

### Freshness signal on the site
Once `last_refreshed_at` is exposed, surface it: org cards get a quiet "Updated 2d ago" badge. Builds trust and proves the pipeline is alive.

### Realtime nice-to-have
Supabase realtime channels can push `entity_changelog` inserts to the open browser. Adds a "Just updated: Coffee & Sawdust posted hours" ticker for free.

---

## Phase 2 — Weeks 2–3: Operational maturity

- Roll to all 521. Watch for cloudflare blocks, rate-limit issues, dead websites.
- `agents/health_dashboard.html` (still static, reads `agent_runs` + `entity_freshness` from Supabase) showing per-entity refresh recency, error counts, daily cost.
- Owner-submitted overrides: simple `/claim/<entity-id>` page → email verification → row in `entity_overrides`. Overrides win in the `entity_full` view.
- Notification webhook (Slack/email) on: new event detected, contacts changed, business looks closed (no successful scrape in 14d).
- Add pgvector column on `entities`: embed `summary || services || categories`. Lays the groundwork for Phase 4 matching.

---

## Phase 3 — Ad bidding (~1–2 weeks once Phase 1 stable)

The Supabase foundation makes this dramatically smaller than v1 of the plan estimated.

**Tables already sketched above** (`ad_slots`, `ad_bids`, `ad_impressions`, `advertisers`).

**Auction logic:** one Supabase Edge Function (Deno) `select-ad-for-slot(slot_id)`:
- SELECT highest active bid for slot where `period` covers now()
- INSERT into `ad_impressions` (for billing)
- Return creative URL + click-through URL
- Falls back to chamber-default if no active bid

**Payments:** Stripe Checkout for one-time slot purchases first (simplest); Stripe Connect later if advertisers need self-service portals. Webhook → Edge Function → INSERT into `ad_bids` with `paid_at`.

**Page integration:** site calls the edge function on page load, drops in the returned creative. ~30 LOC in `index.html`.

**Decision deferred:** which slots become ad-eligible. Wait until the dashboard is alive with real entities and you can see where attention actually goes.

---

## Phase 4 — Membership / fine-tuned personas (~2 weeks)

Supabase Auth gives us this nearly free.

**Sign-up flow:** magic link or Google OAuth. New user → row in `auth.users` → trigger creates `profiles` row.

**Profile schema:**
```sql
create table profiles (
  id uuid primary key references auth.users on delete cascade,
  display_name text,
  personas text[],                 -- can pick multiple
  interests text[],                -- vegan, dogs, live-music, ...
  household jsonb,                 -- {kids:[ages...], adults:n, pets:[...]}
  radius_miles int default 5,
  embedding vector(1536),          -- derived from interests + saved orgs
  created_at timestamptz default now()
);

create table saved_orgs (
  user_id uuid references auth.users on delete cascade,
  entity_id text references entities on delete cascade,
  saved_at timestamptz default now(),
  primary key (user_id, entity_id)
);
```

**Matching upgrade:** signed-out users get current keyword-on-categories matching. Signed-in users get pgvector cosine similarity between `profiles.embedding` and `entities.embedding`, blended with explicit interest filters. Falls back to keyword if embedding missing.

**Free tier still works without an account.** Membership unlocks: saved orgs, RSVP, personalized email digest (Resend), hide-categories-I-don't-care-about. Could later monetize as $3/mo "supporter" tier.

---

## What to build today, in order

1. **Spin up Supabase project + run schema SQL** (~30 min) — pin the contract first.
2. **Backfill 521 entities** from existing JSON via `scripts/backfill_from_chamber_json.py` (~1 hr).
3. **Build minimal `agents/orchestrator.py` + 2 scouts** (website + Google search) and run against 5 test entities (~2 hrs).
4. **Rewrite `index.html` data layer** to use Supabase JS client (~2 hrs).
5. **Verify end-to-end**: dashboard renders all 521, modal shows enriched data for the 5, cards show "Updated Xh ago" (~30 min).
6. **Add the GH Actions cron**, manual-trigger only at first (~1 hr). Flip to scheduled once trusted.

That's 6–10 hrs, end-to-end shippable, and the foundation supports every later phase without rework.

---

## Open decisions before Phase 1

- **Search API for scouts** — Brave Search ($3/1k queries), SerpAPI ($75/mo), or self-hosted SearXNG. Recommend Brave to start.
- **Social scraping legality** — FB/IG aggressively block scrapers. Safer: official Graph API for FB pages we get authorized for, public RSS where available, and the social URLs we already have from the chamber. Don't build on scraping that'll break.
- **Storage choice** — Cloudinary stays for current images (transforms are great). Use Supabase Storage only for owner-uploaded content (claim flow, ad creatives), so a single auth controls write access.
- **Where the agent cron runs** — GH Actions (free, 6h max) vs. Supabase pg_cron triggering edge functions (no Python, all SQL/TS) vs. a $5 Hetzner box. Recommend GH Actions until you outgrow it; pg_cron for housekeeping (mark stale entities, etc.) inside the DB.
- **Anon key exposure** — it's safe to ship in the static page *if* RLS is correct on every table from day one. Audit RLS before going live.

---

## What changes vs. v1 of this plan

| | v1 (JSON in git) | v2 (Supabase) |
|---|---|---|
| Storage | Files in repo | Postgres |
| Writes | git commits | UPSERT |
| Concurrency | Merge conflicts | Transactional |
| Querying | Client-side filter on full payload | SQL |
| Auth (Phase 4) | Forces a rewrite | Built in |
| Ads (Phase 3) | Forces a rewrite | Edge functions + tables |
| Time today | 4–6 hrs | 6–10 hrs |
| Time saved later | — | ~3 weeks of Phase 3/4 setup |
| Site identity | Single self-contained file | Static frontend + public API |
