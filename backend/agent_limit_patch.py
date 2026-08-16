"""Temporary validation-only agent cap for the Market Simulator test.

This patch is intentionally isolated so it can be removed after validation.
Production target after the test remains 15 agents / 2 rounds.
"""

from app.services.zep_entity_reader import ZepEntityReader, FilteredEntities

MAX_TEST_AGENTS = 20


def _select_diverse_entities(entities, limit):
    if len(entities) <= limit:
        return entities

    keywords = (
        "marketing", "produto", "product", "pricing", "preço", "price",
        "analista", "analyst", "gestor", "manager", "profissional", "professional",
    )

    def score(entity):
        text = " ".join([
            str(getattr(entity, "name", "")),
            str(getattr(entity, "summary", "")),
            " ".join(str(x) for x in getattr(entity, "labels", []) or []),
        ]).lower()
        return sum(1 for keyword in keywords if keyword in text)

    ranked = sorted(entities, key=score, reverse=True)

    # Preserve diversity across entity types while prioritizing the three
    # target audiences for this validation: Marketing, Produto and Pricing.
    preferred = []
    other = []
    for entity in ranked:
        text = " ".join([
            str(getattr(entity, "name", "")),
            str(getattr(entity, "summary", "")),
            " ".join(str(x) for x in getattr(entity, "labels", []) or []),
        ]).lower()
        if any(k in text for k in ("marketing", "produto", "product", "pricing", "preço", "price")):
            preferred.append(entity)
        else:
            other.append(entity)

    # Start with the strongest target-audience entities, then fill remaining
    # slots from the rest so the test remains representative of the graph.
    selected = (preferred + other)[:limit]
    return selected


_original_filter = ZepEntityReader.filter_defined_entities


def _limited_filter(self, *args, **kwargs):
    result = _original_filter(self, *args, **kwargs)
    if len(result.entities) <= MAX_TEST_AGENTS:
        return result

    selected = _select_diverse_entities(result.entities, MAX_TEST_AGENTS)
    selected_types = {e.get_entity_type() or "Entity" for e in selected}

    return FilteredEntities(
        entities=selected,
        entity_types=selected_types,
        total_count=result.total_count,
        filtered_count=len(selected),
    )


_limited_filter._mirofish_test_agent_cap = True
ZepEntityReader.filter_defined_entities = _limited_filter
