"""Temporary test-mode patch for the Market Simulator validation run.

This file is loaded by Python at startup and limits the entity set used by the
existing MiroFish simulation pipeline. It is intentionally isolated here so
we can remove it after the validation test and restore the production setup.

Current test target: 20 agents. Production target after validation: 15 agents.
"""

import os
import sys
import importlib.abc
import importlib.machinery
import importlib.util

MAX_AGENTS = int(os.environ.get("MIROFISH_MAX_AGENTS", "20"))


def _select_diverse_entities(entities, limit):
    if len(entities) <= limit:
        return entities

    # Prefer entities that look like the three intended buyer groups, then
    # distribute the remaining slots across entity types so one type cannot
    # consume the whole test population.
    keywords = (
        "marketing", "produto", "product", "pricing", "preço", "price",
        "analista", "analyst", "gestor", "manager", "profissional", "professional"
    )

    def score(entity):
        text = " ".join([
            str(getattr(entity, "name", "")),
            str(getattr(entity, "summary", "")),
            " ".join(str(x) for x in getattr(entity, "labels", []) or []),
        ]).lower()
        return sum(1 for keyword in keywords if keyword in text)

    ranked = sorted(entities, key=score, reverse=True)

    # Build buckets by entity type while preserving the relevance ranking.
    buckets = {}
    for entity in ranked:
        entity_type = entity.get_entity_type() or "Entity"
        buckets.setdefault(entity_type, []).append(entity)

    selected = []
    bucket_lists = list(buckets.values())
    index = 0
    while len(selected) < limit and bucket_lists:
        bucket = bucket_lists[index % len(bucket_lists)]
        if bucket:
            selected.append(bucket.pop(0))
        bucket_lists = [b for b in bucket_lists if b]
        index += 1

    return selected[:limit]


class _PatchLoader(importlib.abc.Loader):
    def __init__(self, original_loader, patcher):
        self.original_loader = original_loader
        self.patcher = patcher

    def create_module(self, spec):
        if hasattr(self.original_loader, "create_module"):
            return self.original_loader.create_module(spec)
        return None

    def exec_module(self, module):
        self.original_loader.exec_module(module)
        self.patcher(module)


class _PatchFinder(importlib.abc.MetaPathFinder):
    TARGET = "backend.app.services.zep_entity_reader"

    def find_spec(self, fullname, path=None, target=None):
        if fullname != self.TARGET:
            return None

        # Avoid recursively finding the same module through this finder.
        try:
            sys.meta_path.remove(self)
        except ValueError:
            pass
        try:
            spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        finally:
            sys.meta_path.insert(0, self)

        if not spec or not spec.loader:
            return spec

        return importlib.util.spec_from_loader(
            fullname,
            _PatchLoader(spec.loader, self._patch),
            origin=spec.origin,
        )

    @staticmethod
    def _patch(module):
        original = module.ZepEntityReader.filter_defined_entities

        if getattr(original, "_mirofish_agent_limit", False):
            return

        def limited_filter(self, *args, **kwargs):
            result = original(self, *args, **kwargs)
            if MAX_AGENTS <= 0 or len(result.entities) <= MAX_AGENTS:
                return result

            selected = _select_diverse_entities(result.entities, MAX_AGENTS)
            selected_types = {e.get_entity_type() or "Entity" for e in selected}

            # Rebuild the existing dataclass rather than changing the rest of
            # the simulation pipeline. Every downstream component therefore
            # sees exactly MAX_AGENTS entities/profiles.
            return module.FilteredEntities(
                entities=selected,
                entity_types=selected_types,
                total_count=result.total_count,
                filtered_count=len(selected),
            )

        limited_filter._mirofish_agent_limit = True
        module.ZepEntityReader.filter_defined_entities = limited_filter


# Install the hook only when the test limit is enabled.
if MAX_AGENTS > 0:
    sys.meta_path.insert(0, _PatchFinder())
