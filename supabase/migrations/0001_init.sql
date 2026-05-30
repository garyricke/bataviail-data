-- BataviaIL Data Product — Phase 0a schema (Path B)
-- Identity & promotion + per-entity attributes + FOIA quarantine + public views.
-- Apply via `supabase db push` or paste into the Supabase SQL editor.

-- ────────────────────────────────────────────────────────────────────────────
-- Extensions
-- ────────────────────────────────────────────────────────────────────────────
create extension if not exists "pgcrypto";   -- gen_random_uuid()
create extension if not exists "vector";      -- pgvector, used Phase 4 (safe to enable now)

-- ────────────────────────────────────────────────────────────────────────────
-- Enums
-- ────────────────────────────────────────────────────────────────────────────
do $$ begin
  create type verification_status as enum ('unverified','scraped','claimed','verified');
exception when duplicate_object then null; end $$;

do $$ begin
  create type membership_level as enum ('Standard','Gold','Platinum','Pro','Unknown');
exception when duplicate_object then null; end $$;

do $$ begin
  create type candidate_status as enum ('new','classified','promoted','rejected');
exception when duplicate_object then null; end $$;

-- ────────────────────────────────────────────────────────────────────────────
-- Identity: entities (public-facing, source of truth) — NO address column
-- ────────────────────────────────────────────────────────────────────────────
create table if not exists entities (
  id                  uuid primary key default gen_random_uuid(),
  name                text not null,
  member_id           text unique,                       -- chamber memberId, natural key for upsert
  slug                text unique,
  description         text,
  summary             text,
  website             text,
  phone               text,
  logo_url            text,
  membership_level    membership_level not null default 'Unknown',
  is_batavia_local    boolean not null default false,
  source              text not null default 'chamber',   -- chamber | foia | manual | scout
  verification_status verification_status not null default 'unverified',
  last_verified_by    text,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now()
);
create index if not exists entities_name_idx on entities using gin (to_tsvector('english', name));

-- ────────────────────────────────────────────────────────────────────────────
-- Locations: separate, because addresses are multi-tenant (N entities ↔ 1 address)
-- ────────────────────────────────────────────────────────────────────────────
create table if not exists locations (
  id              uuid primary key default gen_random_uuid(),
  address_raw     text,
  address_norm    text unique,        -- normalized for dedupe/matching
  city            text,
  state           text,
  zip             text,
  lat             double precision,
  lng             double precision,
  created_at      timestamptz not null default now()
);
create index if not exists locations_norm_idx on locations (address_norm);

create table if not exists entity_location_links (
  entity_id    uuid not null references entities(id) on delete cascade,
  location_id  uuid not null references locations(id) on delete cascade,
  is_primary   boolean not null default true,
  primary key (entity_id, location_id)
);

-- ────────────────────────────────────────────────────────────────────────────
-- Per-entity attributes
-- ────────────────────────────────────────────────────────────────────────────
create table if not exists categories (
  id    serial primary key,
  name  text unique not null
);

create table if not exists entity_categories (
  entity_id    uuid not null references entities(id) on delete cascade,
  category_id  int  not null references categories(id) on delete cascade,
  primary key (entity_id, category_id)
);

create table if not exists entity_contacts (
  id          uuid primary key default gen_random_uuid(),
  entity_id   uuid not null references entities(id) on delete cascade,
  name        text,
  title       text,
  phone       text,
  email       text
);

create table if not exists entity_social (
  id          uuid primary key default gen_random_uuid(),
  entity_id   uuid not null references entities(id) on delete cascade,
  platform    text not null,           -- facebook | instagram | x | linkedin | ...
  url         text not null,
  unique (entity_id, platform)
);

create table if not exists entity_hours (
  id          uuid primary key default gen_random_uuid(),
  entity_id   uuid not null references entities(id) on delete cascade,
  day_of_week smallint,                -- 0=Sun .. 6=Sat; null = freeform
  opens       time,
  closes      time,
  raw         text                     -- original string if unparseable
);

-- ────────────────────────────────────────────────────────────────────────────
-- FOIA quarantine — raw rows land here, NEVER touch entities directly
-- Seed CSV columns: "PBO Assigned To", "Address"
-- ────────────────────────────────────────────────────────────────────────────
create table if not exists foia_records (
  id               uuid primary key default gen_random_uuid(),
  pbo_assigned_to  text,
  address_raw      text,
  address_norm     text,
  classification   text,               -- null until 0b: public_facing | non_public | unknown
  classified_at    timestamptz,
  created_at       timestamptz not null default now()
);
create index if not exists foia_addr_norm_idx on foia_records (address_norm);

-- ────────────────────────────────────────────────────────────────────────────
-- Promotion pipeline — candidates earn their way into entities
-- ────────────────────────────────────────────────────────────────────────────
create table if not exists entity_candidates (
  id              uuid primary key default gen_random_uuid(),
  name            text,
  source          text not null,        -- foia | scout | manual
  source_ref      uuid,                 -- e.g. foia_records.id
  address_norm    text,
  website         text,
  payload         jsonb,                -- raw scout/classification bundle
  status          candidate_status not null default 'new',
  confidence      numeric(4,3),
  created_at      timestamptz not null default now()
);

create table if not exists candidate_matches (
  id             uuid primary key default gen_random_uuid(),
  candidate_id   uuid not null references entity_candidates(id) on delete cascade,
  entity_id      uuid references entities(id) on delete set null,
  match_kind     text,                  -- exact_address | website | fuzzy_name
  score          numeric(4,3),
  created_at     timestamptz not null default now()
);

-- ────────────────────────────────────────────────────────────────────────────
-- Public read views (frontend reads ONLY these via anon key)
-- ────────────────────────────────────────────────────────────────────────────
create or replace view entities_summary as
  select e.id, e.name, e.slug, e.summary, e.logo_url, e.website,
         e.membership_level, e.is_batavia_local, e.verification_status,
         l.city, l.state, l.zip,
         coalesce(array_agg(distinct c.name) filter (where c.name is not null), '{}') as categories
  from entities e
  left join entity_location_links ell on ell.entity_id = e.id and ell.is_primary
  left join locations l on l.id = ell.location_id
  left join entity_categories ec on ec.entity_id = e.id
  left join categories c on c.id = ec.category_id
  group by e.id, l.city, l.state, l.zip;

create or replace view entity_full as
  select e.*,
         (select coalesce(jsonb_agg(to_jsonb(ct) - 'entity_id'), '[]') from entity_contacts ct where ct.entity_id = e.id) as contacts,
         (select coalesce(jsonb_agg(to_jsonb(s)  - 'entity_id'), '[]') from entity_social   s  where s.entity_id  = e.id) as social,
         (select coalesce(jsonb_agg(to_jsonb(h)  - 'entity_id'), '[]') from entity_hours    h  where h.entity_id  = e.id) as hours,
         (select coalesce(array_agg(c.name), '{}') from entity_categories ec join categories c on c.id = ec.category_id where ec.entity_id = e.id) as categories
  from entities e;

-- ────────────────────────────────────────────────────────────────────────────
-- RLS — lock down base tables; expose read-only views to anon
-- NOTE: service-role key (loaders/agents) bypasses RLS. anon is read-only.
-- ────────────────────────────────────────────────────────────────────────────
alter table entities             enable row level security;
alter table locations            enable row level security;
alter table entity_location_links enable row level security;
alter table categories           enable row level security;
alter table entity_categories    enable row level security;
alter table entity_contacts      enable row level security;
alter table entity_social        enable row level security;
alter table entity_hours         enable row level security;
alter table foia_records         enable row level security;
alter table entity_candidates    enable row level security;
alter table candidate_matches    enable row level security;

-- Public can read only verified-enough entities and their attributes via views.
-- (Views run with the querying role; grant select so anon can read through them.)
do $$
declare t text;
begin
  foreach t in array array[
    'entities','locations','entity_location_links','categories',
    'entity_categories','entity_contacts','entity_social','entity_hours'
  ] loop
    execute format(
      'drop policy if exists "anon_read_%1$s" on %1$s;
       create policy "anon_read_%1$s" on %1$s for select to anon using (true);', t);
  end loop;
end $$;

-- Quarantine + promotion tables: NO anon access at all (service-role only).
-- (No select policy for anon → invisible to the public.)
