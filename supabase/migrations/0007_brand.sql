-- 0007 — Per-entity brand: palette + fonts mined from the entity's own website.
-- Stored as a single jsonb blob on entities (one brand per entity), e.g.
--   {"primary":"#1a3e72","accent":"#e8a13c","text":"#222","bg":"#fff",
--    "font_heading":"Poppins","font_body":"Georgia","confidence":0.8}
-- Powers individualized styling of each entity's panel in the frontend.

alter table entities add column if not exists brand jsonb;

-- Recreate entity_full so e.* picks up the new brand column.
-- (A view's column list is fixed at creation — adding a table column needs a rebuild.)
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

grant select on entity_full to anon, authenticated;
