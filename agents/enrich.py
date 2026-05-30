"""Enrich: turn a raw ScoutBundle into a structured, reviewable ProposedUpdate.

DRY_RUN does deterministic structuring (no LLM). The live path sends the bundle to
Sonnet (deep) or Haiku (routine) and parses structured fields back out.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from agents.config import DRY_RUN, MODEL_CHEAP, MODEL_DEEP
from agents.scout import ScoutBundle


@dataclass
class ProposedUpdate:
    entity_id: str
    entity_name: str
    fields: dict = field(default_factory=dict)   # what would be written
    provenance: list[str] = field(default_factory=list)
    confidence: float = 0.0
    model: str = "dry-run"
    usage: dict = field(default_factory=dict)    # token usage from the LLM call

    @property
    def is_empty(self) -> bool:
        return not self.fields


# ── Live extraction (Claude Sonnet, strict tool use) ──────────────────────────
# The system prompt + tool schema are identical for every entity → they form the
# cacheable PREFIX. The per-entity homepage text is the volatile suffix, placed
# in the user message after the cache breakpoint. (Sonnet 4.6's min cacheable
# prefix is 2048 tokens; this prefix is smaller, so caching activates only if the
# system prompt grows — the cache_control is correct and harmless until then.)
_SYSTEM = (
    "You are a precise data-extraction assistant for a Batavia, IL community "
    "directory. Given the visible text of an organization's homepage, extract "
    "ONLY facts explicitly present on the page. Never invent or infer hours, "
    "services, or details that are not clearly stated. If the page does not state "
    "opening hours, set found_hours=false and return an empty hours array. Keep "
    "the summary factual and under 40 words. Use 24-hour HH:MM times; "
    "day_of_week is 0=Sunday .. 6=Saturday."
)

_TOOL = {
    "name": "record_business_info",
    "description": "Record structured business information extracted from the homepage text.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string", "description": "Factual 1-2 sentence summary of what the org does. Empty string if unclear."},
            "services": {"type": "array", "items": {"type": "string"}, "description": "Distinct services, products, or programs explicitly offered. Empty if none stated."},
            "found_hours": {"type": "boolean", "description": "True ONLY if explicit opening hours appear on the page."},
            "hours": {
                "type": "array",
                "description": "One entry per day with stated hours; empty when found_hours is false.",
                "items": {
                    "type": "object",
                    "properties": {
                        "day_of_week": {"type": "integer", "enum": [0, 1, 2, 3, 4, 5, 6]},
                        "opens": {"type": "string", "description": "HH:MM 24-hour"},
                        "closes": {"type": "string", "description": "HH:MM 24-hour"},
                    },
                    "required": ["day_of_week", "opens", "closes"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["summary", "services", "found_hours", "hours"],
        "additionalProperties": False,
    },
}


def _call_anthropic(model, entity, bundle):
    import anthropic  # imported lazily so dry-run never needs the dep

    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env (.env via override)
    user_content = (
        f"Organization: {entity['name']}\n"
        f"Website: {bundle.final_url}\n"
        f"Page title: {bundle.title}\n\n"
        f"Homepage text:\n{bundle.homepage_text}"
    )
    # No thinking: forcing a specific tool (tool_choice) is incompatible with it.
    return client.messages.create(
        model=model,
        max_tokens=1500,
        system=[{"type": "text", "text": _SYSTEM, "cache_control": {"type": "ephemeral"}}],
        tools=[_TOOL],
        tool_choice={"type": "tool", "name": "record_business_info"},
        messages=[{"role": "user", "content": user_content}],
    )


def _structure(entity, bundle: ScoutBundle, model: str) -> ProposedUpdate:
    fields, prov = {}, []
    if bundle.discovered_hours:
        fields["hours"] = bundle.discovered_hours
        prov.append(f"hours from {bundle.source}")
    if bundle.discovered_social:
        fields["social"] = bundle.discovered_social
        prov.append(f"social from {bundle.source}")
    if bundle.discovered_news:
        fields["news"] = bundle.discovered_news
        prov.append(f"news from {bundle.source}")
    confidence = 0.55 if DRY_RUN else 0.0
    return ProposedUpdate(
        entity_id=entity["id"], entity_name=entity["name"],
        fields=fields, provenance=prov, confidence=confidence, model=model,
    )


async def _enrich_live(entity, bundle, model) -> ProposedUpdate:
    """Send the scraped homepage text to Claude and parse a structured update."""
    if not bundle.homepage_text:
        return ProposedUpdate(entity_id=entity["id"], entity_name=entity["name"], model=model)

    resp = await asyncio.to_thread(_call_anthropic, model, entity, bundle)
    data = next((b.input for b in resp.content if b.type == "tool_use"), {}) or {}

    fields, prov = {}, []
    summary = (data.get("summary") or "").strip()
    if summary:
        fields["summary"] = summary
        prov.append(f"summary from {model}")
    if data.get("services"):
        fields["services"] = data["services"]
        prov.append(f"services from {model}")
    # Only propose hours when the model found explicit ones AND we lack them.
    if data.get("found_hours") and data.get("hours") and not entity["has_hours"]:
        fields["hours"] = data["hours"]
        prov.append(f"hours from {model}")
    # Fold in the scout's deterministic regex discoveries (real, no LLM).
    if bundle.discovered_social:
        fields["social"] = bundle.discovered_social
        prov.append("social from homepage")
    if bundle.discovered_contacts:
        fields["contacts"] = bundle.discovered_contacts
        prov.append("contacts from homepage")

    confidence = 0.80 if "hours" in fields else (0.65 if summary else 0.40)
    u = resp.usage
    return ProposedUpdate(
        entity_id=entity["id"], entity_name=entity["name"],
        fields=fields, provenance=prov, confidence=confidence, model=model,
        usage={
            "input": u.input_tokens, "output": u.output_tokens,
            "cache_read": getattr(u, "cache_read_input_tokens", 0),
            "cache_write": getattr(u, "cache_creation_input_tokens", 0),
        },
    )


async def enrich(entity, bundle: ScoutBundle, *, deep: bool) -> ProposedUpdate:
    model = MODEL_DEEP if deep else MODEL_CHEAP
    if DRY_RUN:
        return _structure(entity, bundle, model="dry-run")
    return await _enrich_live(entity, bundle, model)
