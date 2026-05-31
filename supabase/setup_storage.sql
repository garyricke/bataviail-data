-- One-off storage setup (run via loaders/_common connect, not the migration chain,
-- so storage-schema permission quirks don't block normal migrations).
-- Creates a public 'media' bucket and lets the anon key upload + read it.

insert into storage.buckets (id, name, public)
values ('media', 'media', true)
on conflict (id) do update set public = true;

drop policy if exists "anon_insert_media" on storage.objects;
create policy "anon_insert_media" on storage.objects
  for insert to anon with check (bucket_id = 'media');

drop policy if exists "public_read_media" on storage.objects;
create policy "public_read_media" on storage.objects
  for select using (bucket_id = 'media');
