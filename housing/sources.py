"""Portable city source catalogs for fresh apartment collection."""

from __future__ import annotations

from copy import deepcopy
import importlib.resources
import json
import re
from typing import Mapping

from .collectors import SUPPORTED_ADAPTERS


_CITY_ALIASES = {
    "chicago": "chicago",
    "chicago il": "chicago",
    "chicago illinois": "chicago",
}


def _city_slug(city: str) -> str:
    if not isinstance(city, str) or not city.strip():
        raise ValueError("city is required")
    normalized = re.sub(r"[^a-z0-9]+", " ", city.lower()).strip()
    return _CITY_ALIASES.get(normalized, re.sub(r"\s+", "-", normalized))


def _generic_catalog(city: str) -> dict:
    return {
        "schema_version": "0.2",
        "city": city.strip(),
        "scope_note": "No maintained direct-source catalog yet. Custom sources still work; optional discovery entries are disabled by default.",
        "sources": [
            {
                "id": "homeharvest-optional",
                "name": "Optional Realtor rentals through HomeHarvest",
                "adapter": "homeharvest",
                "enabled": False,
                "catalog_source": True,
                "permission_note": "Optional open-source adapter; upstream access may fail and no proxy or challenge bypass is configured.",
                "max_pages": 1,
                "max_listings": 200,
                "search": {"location": city.strip()},
            },
            {
                "id": "local-source-discovery",
                "name": "Local source discovery needed",
                "adapter": "assisted",
                "enabled": False,
                "catalog_source": True,
                "permission_note": "Placeholder documenting that named local sources must be researched and validated before activation.",
                "assisted_reason": "Add validated public manager or city sources for this city; no generic national coverage claim is made.",
                "max_pages": 1,
                "max_listings": 1,
                "search": {},
            },
        ],
    }


def _load(city: str) -> dict:
    slug = _city_slug(city)
    resource = importlib.resources.files("housing").joinpath("cities", f"{slug}.json")
    try:
        document = json.loads(resource.read_text(encoding="utf-8"))
    except FileNotFoundError:
        document = _generic_catalog(city)
    if not isinstance(document, dict) or not isinstance(document.get("sources"), list):
        raise ValueError(f"Invalid source catalog for {city!r}")
    required = {
        "id", "adapter", "enabled", "permission_note", "max_pages", "max_listings", "search",
    }
    seen: set[str] = set()
    for index, source in enumerate(document["sources"]):
        if not isinstance(source, dict):
            raise ValueError(f"Catalog source {index} must be an object")
        missing = sorted(required - source.keys())
        if missing:
            raise ValueError(f"Catalog source {index} is missing: {', '.join(missing)}")
        if source["id"] in seen:
            raise ValueError(f"Duplicate catalog source id: {source['id']}")
        seen.add(source["id"])
        if source["adapter"] not in SUPPORTED_ADAPTERS:
            raise ValueError(f"Unsupported catalog adapter: {source['adapter']}")
        if source["adapter"] not in ("homeharvest", "assisted") and not source.get("url"):
            raise ValueError(f"Catalog source {source['id']} requires a URL")
        if source.get("catalog_source") is not True:
            raise ValueError(f"Catalog source {source['id']} must set catalog_source=true")
        if not isinstance(source["search"], dict):
            raise ValueError(f"Catalog source {source['id']} search must be an object")
    return document


def source_catalog(city: str) -> list[dict]:
    """Return all known runnable, optional, and assisted sources for a city."""

    return deepcopy(_load(city)["sources"])


def default_sources(city: str, search: Mapping[str, object] | None = None) -> list[dict]:
    """Return enabled runnable sources with a shared search overlaid.

    Source URLs define geography; the shared search filters only known facts.
    Unknown square footage and other unknown facts remain in the review queue.
    """

    if search is not None and not isinstance(search, Mapping):
        raise ValueError("search must be an object")
    result: list[dict] = []
    for source in source_catalog(city):
        if source.get("enabled") is not True:
            continue
        combined = dict(source.get("search", {}))
        if search:
            combined.update({key: value for key, value in search.items() if value is not None})
        source["search"] = combined
        result.append(source)
    return result


__all__ = ["default_sources", "source_catalog"]
