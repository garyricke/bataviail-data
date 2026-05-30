"""Enrich: turn a raw ScoutBundle into a structured, reviewable ProposedUpdate.

DRY_RUN does deterministic structuring (no LLM). The live path sends the bundle to
Sonnet (deep) or Haiku (routine) and parses structured fields back out.
"""
from __future__ import annotations

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

    @property
    def is_empty(self) -> bool:
        return not self.fields


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


async def _enrich_live(entity, bundle, model):  # pragma: no cover - Phase 0b real path
    raise NotImplementedError(
        "Live enrich (Anthropic call + structured parse + prompt caching) lands here "
        "once ANTHROPIC_API_KEY is set and DRY_RUN is off."
    )


async def enrich(entity, bundle: ScoutBundle, *, deep: bool) -> ProposedUpdate:
    model = MODEL_DEEP if deep else MODEL_CHEAP
    if DRY_RUN:
        return _structure(entity, bundle, model="dry-run")
    return await _enrich_live(entity, bundle, model)
