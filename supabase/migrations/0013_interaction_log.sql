-- 0013 — interaction_log: the Stage-2 behavioral signal for persona matching.
--
-- See plan/persona-evolution.md. The directory logs lightweight engagement
-- (persona_selected, org_clicked, …) here so that by the time we want AI/vector
-- matching we already have a supervised corpus. Wired from day one.
--
-- Privacy: anon may INSERT (write-only logging) but may NOT read — analytics
-- stay server-side. No PII is sent by the client (just event_type + small payload).

create table if not exists interaction_log (
  id          uuid primary key default gen_random_uuid(),
  created_at  timestamptz not null default now(),
  event_type  text not null,
  payload     jsonb not null default '{}'
);
create index if not exists interaction_log_type_idx on interaction_log (event_type, created_at);

alter table interaction_log enable row level security;

-- Write-only for the public site: insert allowed, select denied.
drop policy if exists "anon_insert_interaction" on interaction_log;
create policy "anon_insert_interaction" on interaction_log
  for insert to anon, authenticated with check (true);

grant insert on interaction_log to anon, authenticated;
