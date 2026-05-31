"""Re-voice entity descriptions in one cohesive 'Batavia community voice' — each
unique and factual, but together telling a single story of a connected town.

    python -m agents.voice --dry --limit 6      # sample (print before/after, no write)
    DRY_RUN=0 python -m agents.voice --limit 50  # re-voice 50
    DRY_RUN=0 python -m agents.voice             # re-voice all
"""
from __future__ import annotations

import argparse

from psycopg.types.json import Json

from agents.config import MODEL_DEEP
from agents.db import connect

# The locked editorial north star — the text counterpart of the photo house style.
COMMUNITY_VOICE = (
    "You write short directory descriptions for organizations in Batavia, Illinois — "
    "a historic Fox River town with a walkable downtown, a riverside Riverwalk, and a "
    "close-knit, neighborly character.\n\n"
    "There is ONE house voice across every description, so that read together they tell a "
    "single, connected story of community — yet each description stays unique and specific to "
    "its subject. For the organization given, write a description that:\n"
    "- Is factual and specific to THIS organization, using only the facts provided. Never invent "
    "details, founders, dates, or claims.\n"
    "- Quietly places it within Batavia's shared life — its small part in the town's everyday "
    "fabric, its place among neighbors. Let that belonging come through the voice, not a slogan; "
    "do NOT force 'Fox River' or 'downtown' into every one.\n"
    "- Carries a warm, grounded, unpretentious tone — like a proud local introducing a neighbor.\n"
    "- Varies its structure and opening words. Avoid clichés ('nestled', 'hidden gem', "
    "'one-stop shop', 'something for everyone') and never start like the previous description.\n"
    "- Is 1–2 sentences, about 30–40 words.\n\n"
    "Output ONLY the description text — no quotes, label, or preamble."
)


def _client():
    import anthropic
    return anthropic.Anthropic()


def revoice(client, name, cats, summary, services) -> str:
    user = (
        f"Organization: {name}\n"
        f"Type: {', '.join(cats) if cats else 'local organization'}\n"
        f"Known facts: {summary or '(little is known beyond its name and that it is part of Batavia)'}\n"
        f"Notable offerings: {', '.join(services[:8]) if services else '—'}\n\n"
        "Write the description now."
    )
    r = client.messages.create(
        model=MODEL_DEEP, max_tokens=220,
        system=COMMUNITY_VOICE,
        messages=[{"role": "user", "content": user}],
    )
    return next((b.text for b in r.content if b.type == "text"), "").strip().strip('"').strip()


def fetch_targets(cur, limit, randomize):
    order = "random()" if randomize else "e.name"
    cur.execute(f"""
        select e.id, e.name, coalesce(e.summary,''),
          coalesce((select array_agg(c.name) from entity_categories ec join categories c on c.id=ec.category_id where ec.entity_id=e.id),'{{}}'),
          coalesce((select array_agg(sv.name) from entity_services sv where sv.entity_id=e.id),'{{}}')
        from entities e
        where e.summary is not null and length(trim(e.summary))>0
        order by {order} {('limit ' + str(limit)) if limit else ''}
    """)
    return cur.fetchall()


def run(args):
    client = _client()
    with connect() as c, c.cursor() as cur:
        targets = fetch_targets(cur, args.limit, args.dry or args.random)
    print(f"re-voicing {len(targets)} description(s){' (DRY — no writes)' if args.dry else ''}\n")
    for eid, name, summary, cats, services in targets:
        new = revoice(client, name, list(cats), summary, list(services))
        if args.dry:
            print(f"● {name}\n   before: {summary[:150]}\n   after : {new}\n")
        else:
            with connect() as c, c.cursor() as cur:
                cur.execute("select summary from entities where id=%s", (eid,))
                old = cur.fetchone()[0]
                cur.execute("update entities set summary=%s, updated_at=now() where id=%s", (new, eid))
                cur.execute("""insert into entity_changelog (entity_id, source, model, changes)
                               values (%s,'revoice',%s,%s)""",
                            (eid, MODEL_DEEP, Json({"summary": {"old": old, "new": new}})))
                c.commit()
            print(f"✓ {name}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--dry", action="store_true", help="print before/after, write nothing")
    p.add_argument("--random", action="store_true", help="random order (good for sampling)")
    run(p.parse_args())


if __name__ == "__main__":
    main()
