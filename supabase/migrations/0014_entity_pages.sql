-- 0014 — entity_pages: Tier-3 bespoke pages stored as DATA.
--
-- See web/plan-landing-pages.html §4-5. A bespoke Pro page is a versioned
-- section spec (layout_json), not a hand-built file: custom copy, per-page
-- brand tokens, curated imagery, block order. landing.html renders the
-- highest published version when ?theme=bespoke; agents/claim-flow author
-- rows here via the service role. Nothing on the public site can write.
--
-- layout_json shape (v1):
--   { "brand":  { bg, surface, ink, muted, line, accent, accent2,
--                 fontDisplay, fontAccent, fontBody, google: [] },
--     "blocks": [ { "type": "hero|facts|story|quote|split|team|gallery|visit", ... } ] }

create table if not exists entity_pages (
  id          uuid primary key default gen_random_uuid(),
  entity_id   uuid not null references entities(id) on delete cascade,
  tier        int  not null default 3,
  theme_key   text not null default 'bespoke',
  layout_json jsonb not null default '{}',
  published   boolean not null default false,
  version     int  not null default 1,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  unique (entity_id, version)
);
create index if not exists entity_pages_entity_idx on entity_pages (entity_id, published, version desc);

alter table entity_pages enable row level security;

-- Public site may read PUBLISHED pages only; drafts stay invisible.
drop policy if exists "anon_read_published_pages" on entity_pages;
create policy "anon_read_published_pages" on entity_pages
  for select to anon, authenticated using (published);

grant select on entity_pages to anon, authenticated;
