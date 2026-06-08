-- 0012 — event-driven upload processing.
--
-- GitHub's scheduled cron is throttled (a */5 schedule actually fires ~hourly),
-- so an uploaded photo can sit unprocessed for a long time. Instead, fire the
-- GitHub Actions workflow the instant a row lands in photo_uploads: an AFTER
-- INSERT trigger uses pg_net to call GitHub's repository_dispatch API.
--
-- The GitHub token is read from Supabase Vault (secret name 'github_pat') — it
-- is never stored in this migration or in any committed file.
--
-- SAFETY: the trigger function swallows all errors and skips when no token is
-- present, so it can be deployed BEFORE the secret exists and can never block
-- an upload insert, no matter what GitHub or pg_net does.

create extension if not exists pg_net;

create or replace function public.notify_github_new_upload()
returns trigger
language plpgsql
security definer
set search_path = public, vault, net, extensions
as $$
declare
  tok text;
begin
  begin
    select decrypted_secret into tok
      from vault.decrypted_secrets where name = 'github_pat' limit 1;

    if tok is not null and length(tok) > 0 then
      perform net.http_post(
        url := 'https://api.github.com/repos/garyricke/bataviail-data/dispatches',
        headers := jsonb_build_object(
          'Authorization', 'Bearer ' || tok,
          'Accept', 'application/vnd.github+json',
          'User-Agent', 'supabase-photo-uploads',
          'Content-Type', 'application/json'
        ),
        body := jsonb_build_object('event_type', 'new_upload')
      );
    end if;
  exception when others then
    -- Never let a dispatch failure block the upload itself.
    null;
  end;
  return new;
end;
$$;

drop trigger if exists photo_uploads_notify_github on photo_uploads;
create trigger photo_uploads_notify_github
  after insert on photo_uploads
  for each row execute function public.notify_github_new_upload();
