-- 0011 — Multiple images per entity. entities.hero stays as the PRIMARY image
-- (shown on the card + grid); entity_media holds the full gallery.

create table if not exists entity_media (
  id          uuid primary key default gen_random_uuid(),
  entity_id   uuid not null references entities(id) on delete cascade,
  url         text not null,
  kind        text not null default 'community',   -- community | enhanced | generated
  source      text,
  caption     text,
  sort_order  int  not null default 0,
  created_at  timestamptz not null default now(),
  unique (entity_id, url)                            -- idempotent backfill / no dup uploads
);
create index if not exists entity_media_entity_idx on entity_media (entity_id, sort_order, created_at);

alter table entity_media enable row level security;
drop policy if exists "anon_read_entity_media" on entity_media;
create policy "anon_read_entity_media" on entity_media for select to anon using (true);
grant select on entity_media to anon, authenticated;

-- Backfill: every existing hero becomes the entity's first gallery image.
insert into entity_media (entity_id, url, kind, source, sort_order)
select id, hero->>'url', coalesce(hero->>'kind','community'), hero->>'source', 0
from entities where hero is not null and hero->>'url' is not null
on conflict (entity_id, url) do nothing;

-- Expose the gallery in the read view.
drop view if exists entity_full;
create view entity_full with (security_invoker = true) as
  select e.*,
         (select coalesce(jsonb_agg(to_jsonb(ct) - 'entity_id'), '[]') from entity_contacts ct where ct.entity_id = e.id) as contacts,
         (select coalesce(jsonb_agg(to_jsonb(s)  - 'entity_id'), '[]') from entity_social   s  where s.entity_id  = e.id) as social,
         (select coalesce(jsonb_agg(to_jsonb(h)  - 'entity_id' - 'id'), '[]') from entity_hours h where h.entity_id = e.id) as hours,
         (select coalesce(array_agg(c.name), '{}') from entity_categories ec join categories c on c.id = ec.category_id where ec.entity_id = e.id) as categories,
         (select coalesce(array_agg(sv.name order by sv.name), '{}') from entity_services sv where sv.entity_id = e.id) as services,
         (select coalesce(jsonb_agg(to_jsonb(ev) - 'entity_id' - 'dedup_key' - 'found_at' order by ev.starts_at nulls last), '[]')
            from entity_events ev where ev.entity_id = e.id and (ev.starts_at is null or ev.starts_at >= now())) as events,
         (select jsonb_build_object('address', l.address_raw, 'city', l.city, 'state', l.state, 'zip', l.zip)
            from entity_location_links ell join locations l on l.id = ell.location_id
            where ell.entity_id = e.id order by ell.is_primary desc limit 1) as location,
         (select coalesce(jsonb_agg(jsonb_build_object('url', m.url, 'kind', m.kind, 'caption', m.caption)
                          order by m.sort_order, m.created_at), '[]')
            from entity_media m where m.entity_id = e.id) as media
  from entities e;

grant select on entity_full to anon, authenticated;
