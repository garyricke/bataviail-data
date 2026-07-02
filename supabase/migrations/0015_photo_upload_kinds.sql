-- 0015 — photo_uploads.kind: the capture PWA now shoots more than place heroes.
--
-- kind ∈ 'place' (default — hero/gallery pipeline, unchanged) · 'person'
-- (future: AI-polished headshots → entity_pages team blocks) · 'event'
-- (future: photo assigned to an entity_events row → bespoke event cards).
-- event_id is the future assignment target for kind='event' captures.
-- The existing worker (agents/process_uploads.py) only processes kind='place';
-- person/event rows queue until their pipelines exist.

alter table photo_uploads add column if not exists kind text not null default 'place';
alter table photo_uploads add column if not exists event_id uuid references entity_events(id) on delete set null;
create index if not exists photo_uploads_kind_idx on photo_uploads (kind, status);
