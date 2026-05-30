-- 0006 — entity_events: time-bound happenings collected from entity websites.
--
-- Unlike static fields (hours/services), events expire — so we store dates and
-- DERIVE upcoming/past in the read view (no stale status flag). Dedup is by
-- (entity_id, dedup_key) where dedup_key = normalized title + date, so re-runs
-- and multiple sources collapse onto one row.

create table if not exists entity_events (
  id           uuid primary key default gen_random_uuid(),
  entity_id    uuid not null references entities(id) on delete cascade,
  title        text not null,
  description  text,
  starts_at    timestamptz,                 -- null when date is unknown/TBD
  ends_at      timestamptz,
  all_day      boolean not null default false,
  location     text,
  url          text,
  price        text,
  source       text not null default 'entity_site',
  dedup_key    text not null,               -- normalize(title)+'|'+date
  found_at     timestamptz not null default now(),
  unique (entity_id, dedup_key)
);
create index if not exists entity_events_entity_idx on entity_events (entity_id, starts_at);

-- Public directory content → anon-readable.
alter table entity_events enable row level security;
drop policy if exists "anon_read_entity_events" on entity_events;
create policy "anon_read_entity_events" on entity_events for select to anon using (true);
grant select on entity_events to anon, authenticated;

-- Surface UPCOMING events (or undated) in the entity_full read view, soonest first.
-- DROP+CREATE (not REPLACE) because we're adding a column — REPLACE can't restructure.
drop view if exists entity_full;
create view entity_full with (security_invoker = true) as
  select e.*,
         (select coalesce(jsonb_agg(to_jsonb(ct) - 'entity_id'), '[]') from entity_contacts ct where ct.entity_id = e.id) as contacts,
         (select coalesce(jsonb_agg(to_jsonb(s)  - 'entity_id'), '[]') from entity_social   s  where s.entity_id  = e.id) as social,
         (select coalesce(jsonb_agg(to_jsonb(h)  - 'entity_id' - 'id'), '[]') from entity_hours h where h.entity_id = e.id) as hours,
         (select coalesce(array_agg(c.name), '{}') from entity_categories ec join categories c on c.id = ec.category_id where ec.entity_id = e.id) as categories,
         (select coalesce(array_agg(sv.name order by sv.name), '{}') from entity_services sv where sv.entity_id = e.id) as services,
         (select coalesce(jsonb_agg(to_jsonb(ev) - 'entity_id' - 'dedup_key' - 'found_at' order by ev.starts_at nulls last), '[]')
            from entity_events ev
            where ev.entity_id = e.id and (ev.starts_at is null or ev.starts_at >= now())) as events
  from entities e;

-- Re-grant anon read on the recreated view (DROP removed the prior grant).
grant select on entity_full to anon, authenticated;
