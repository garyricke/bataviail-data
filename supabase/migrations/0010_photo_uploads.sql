-- 0010 — Capture queue. The PWA inserts a row per photo (raw image already in
-- Storage); the worker processes pending rows (enhance → hero, geocode → address).

create table if not exists photo_uploads (
  id            uuid primary key default gen_random_uuid(),
  entity_id     uuid references entities(id) on delete set null,
  entity_name   text,                       -- set when shooting a not-yet-listed place
  storage_path  text not null,              -- path within the 'media' bucket
  gps_lat       double precision,
  gps_lng       double precision,
  status        text not null default 'pending',   -- pending | done | error
  note          text,
  created_at    timestamptz not null default now(),
  processed_at  timestamptz
);
create index if not exists photo_uploads_status_idx on photo_uploads (status, created_at);

-- The capture page uses the anon key: allow it to insert and read queue rows.
-- (v1 single-user behind a page passcode; tighten with Auth later.)
alter table photo_uploads enable row level security;
drop policy if exists "anon_insert_uploads" on photo_uploads;
create policy "anon_insert_uploads" on photo_uploads for insert to anon with check (true);
drop policy if exists "anon_read_uploads" on photo_uploads;
create policy "anon_read_uploads" on photo_uploads for select to anon using (true);
grant insert, select on photo_uploads to anon, authenticated;
