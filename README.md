# BataviaIL — Data Product

A Supabase-backed community-data platform for Batavia, IL. **Data first**: a
Postgres source-of-truth grows via an agent swarm; the public site is a thin
read-only frontend over database views. This is *not* the old single-file
`index.html` webpage — that lives in `../bataviail-ai2026` and is presentation only.

The canonical design is **Path B** in [`plan/build-plan.md`](plan/build-plan.md).
Read it before changing schema or scoping phases.

## Data-first build sequence (Path B, Phase 0a)

The interface comes **last**, on purpose. Order:

1. **Scaffold** — repo structure + seed files copied in. ✅ (you are here)
2. **Stand up Supabase** — create a project, apply `supabase/migrations/`.
3. **Load chamber → `entities`** — `loaders/load_chamber.py` (521 verified-backbone orgs).
4. **Load FOIA → `foia_records` quarantine** — `loaders/load_foia_quarantine.py` (5,455 raw rows; nothing touches `entities`).
5. **Verify the data layer in isolation** — query views, confirm counts. The "prove the data" gate. No UI.
6. **Agent prototype (Phase 0b)** — 5 pilots + FOIA classification + ~175 promotions.
7. **Build the interface** — frontend reads `entities_summary` / `entity_full` via the anon key.

## Layout

| Path | What |
|---|---|
| `plan/` | Canonical build plan (`build-plan.md`), agent spec, original goal |
| `data/seed/` | Source-of-truth inputs — immutable, version-controlled |
| `supabase/migrations/` | Schema as SQL |
| `loaders/` | Idempotent seed → DB scripts |
| `agents/` | The swarm (orchestrator + scouts), Phase 0b+ |

## Seed data

| File | Rows | Becomes |
|---|---|---|
| `data/seed/chamber.json` | 291 local + 230 regional = 521 | `entities` (verified backbone) |
| `data/seed/foia_inspections.csv` | 5,455 (`PBO Assigned To`, `Address`) | `foia_records` (quarantine → promote ~175) |
| `data/seed/personas.md` | 7 personas | Phase 4 personalization |
| `data/seed/brand-colors.svg` | palette | frontend (Phase 7) |

## Getting started

```bash
cp .env.example .env        # then fill in Supabase keys (see step 2 below)
```

**Step 2 needs your hands:** create a Supabase project at https://supabase.com,
copy the URL + anon + service-role keys into `.env`, then apply the migration
(via `supabase db push` or pasting `supabase/migrations/0001_init.sql` into the
SQL editor). Everything after that is scripted.
