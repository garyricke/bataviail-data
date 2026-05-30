-- 0005 — Add agent-collected services to the entity_full read view.
-- entity_services was written by the enrich pipeline (0004) but wasn't yet
-- surfaced in the public read view the frontend consumes. This adds it.

drop view if exists entity_full;
create view entity_full with (security_invoker = true) as
  select e.*,
         (select coalesce(jsonb_agg(to_jsonb(ct) - 'entity_id'), '[]') from entity_contacts ct where ct.entity_id = e.id) as contacts,
         (select coalesce(jsonb_agg(to_jsonb(s)  - 'entity_id'), '[]') from entity_social   s  where s.entity_id  = e.id) as social,
         (select coalesce(jsonb_agg(to_jsonb(h)  - 'entity_id' - 'id'), '[]') from entity_hours h where h.entity_id = e.id) as hours,
         (select coalesce(array_agg(c.name), '{}') from entity_categories ec join categories c on c.id = ec.category_id where ec.entity_id = e.id) as categories,
         (select coalesce(array_agg(sv.name order by sv.name), '{}') from entity_services sv where sv.entity_id = e.id) as services
  from entities e;

grant select on entity_full to anon, authenticated;
