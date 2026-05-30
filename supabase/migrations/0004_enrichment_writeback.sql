-- 0004 — Tables for the agent write-back path (auto-apply, audited).
--
-- Data-build phase: agents write enrichment DIRECTLY to live entity tables (no
-- human review gate yet). The audit trail is what keeps this safe — every write
-- records an entity_changelog row (old→new, model, confidence), so any change is
-- traceable and reversible. Review-gating can be layered on later (Phase 2).

-- Services / programs / offerings extracted from a homepage (public directory data).
create table if not exists entity_services (
  id         uuid primary key default gen_random_uuid(),
  entity_id  uuid not null references entities(id) on delete cascade,
  name       text not null,
  unique (entity_id, name)
);

-- Audit trail — one row per applied agent change set. INTERNAL (not anon-readable).
create table if not exists entity_changelog (
  id          uuid primary key default gen_random_uuid(),
  entity_id   uuid not null references entities(id) on delete cascade,
  changed_at  timestamptz not null default now(),
  source      text not null,              -- e.g. 'agent_enrich'
  model       text,
  confidence  numeric(4,3),
  changes     jsonb not null              -- {field: {old, new} | {new_count} | [..]}
);
create index if not exists changelog_entity_idx on entity_changelog (entity_id, changed_at desc);

-- Freshness / scheduling state per entity. INTERNAL (ops, not anon-readable).
create table if not exists entity_freshness (
  entity_id             uuid primary key references entities(id) on delete cascade,
  last_checked_at       timestamptz,
  last_deep_enriched_at timestamptz,        -- distinguishes cheap-check vs deep-enrich
  last_content_hash     text,
  failure_streak        int not null default 0,
  next_due_at           timestamptz
);

-- RLS: entity_services is public directory content (anon-readable); changelog +
-- freshness are internal (no anon policy → invisible to anon). service_role gets
-- all three automatically via the default privileges set in 0002.
alter table entity_services  enable row level security;
alter table entity_changelog enable row level security;
alter table entity_freshness enable row level security;

drop policy if exists "anon_read_entity_services" on entity_services;
create policy "anon_read_entity_services" on entity_services for select to anon using (true);
grant select on entity_services to anon, authenticated;
