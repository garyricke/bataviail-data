-- 0009 — Surface the primary address in entity_full (addresses live in `locations`,
-- linked via entity_location_links, but were never exposed in the read view).

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
            where ev.entity_id = e.id and (ev.starts_at is null or ev.starts_at >= now())) as events,
         (select jsonb_build_object('address', l.address_raw, 'city', l.city, 'state', l.state, 'zip', l.zip)
            from entity_location_links ell join locations l on l.id = ell.location_id
            where ell.entity_id = e.id order by ell.is_primary desc limit 1) as location
  from entities e;

grant select on entity_full to anon, authenticated;
