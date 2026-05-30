-- 0003 — scout_cache: raw fetch cache keyed by URL.
--
-- Powers the Path B "cheap freshness check": re-fetch a URL, hash the body, and
-- compare to the stored content_hash. Unchanged → no enrichment needed. This is
-- an agent OPS table (service_role only) — it holds raw scraped HTML, never
-- public-facing data, so anon gets no access (no grant; default privileges from
-- 0002 grant it to service_role automatically).

create table if not exists scout_cache (
  url           text primary key,
  status        int,
  etag          text,
  content_hash  text,           -- sha256 of body, for change detection
  body          text,           -- raw response body (HTML)
  fetched_at    timestamptz not null default now()
);

alter table scout_cache enable row level security;  -- no anon policy → invisible to anon
