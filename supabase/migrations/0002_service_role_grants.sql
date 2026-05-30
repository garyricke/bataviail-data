-- 0002 — Grant service_role full access to the public schema.
--
-- service_role is the trusted SERVER role behind the secret key (sb_secret_…):
-- agents read quarantine, classify, and write candidates through it. It already
-- has BYPASSRLS, but privilege GRANTs are a separate layer — and because the
-- project was created with "auto-expose new tables" OFF, our tables had no
-- service_role grants. This adds them, including the quarantine tables (safe:
-- the secret key is server-only and never ships to a client).
--
-- anon stays limited to the 8 public tables + 2 views from 0001. This file does
-- NOT touch anon.

grant usage on schema public to service_role;
grant all privileges on all tables    in schema public to service_role;
grant all privileges on all sequences in schema public to service_role;

-- Future tables/sequences created by the owner inherit the same grants, so we
-- never re-hit the 403 when new tables are added in later phases.
alter default privileges in schema public grant all on tables    to service_role;
alter default privileges in schema public grant all on sequences to service_role;
