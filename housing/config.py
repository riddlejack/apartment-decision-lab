"""Portable configuration; household destinations stay in the local workspace."""
import json
import math
import os
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def validate_config(config):
    if not isinstance(config, dict):
        raise ValueError("Configuration must be an object")
    try:
        ZoneInfo(config.get("timezone", "America/Chicago"))
    except (ZoneInfoNotFoundError, TypeError):
        raise ValueError("Use an IANA timezone, for example America/Chicago") from None
    if config.get("currency", "USD") != "USD":
        raise ValueError("This release supports USD listings; other currencies need an adapter")
    from .search import validate_search
    validate_search(config.setdefault("search", {}))
    if not isinstance(config.get("city", ""), str) or len(config.get("city", "")) > 200:
        raise ValueError("city must be text of at most 200 characters")
    people = config.get("people", [])
    if not isinstance(people, list) or len(people) > 20:
        raise ValueError("people must be an array of at most 20 people")
    ids = set()
    for person in people:
        if (not isinstance(person, dict) or not isinstance(person.get("id"), str)
                or not person["id"].strip() or person["id"] != person["id"].strip()
                or person["id"] in ids):
            raise ValueError("Every person needs a unique id")
        ids.add(person["id"])
        modes = person.get("modes", [])
        if not isinstance(modes, list) or not modes or any(mode not in ("walk", "bike", "transit", "drive") for mode in modes):
            raise ValueError("Each person needs allowed modes: walk, bike, transit and/or drive")
        cap = person.get("max_minutes")
        if cap is not None and (isinstance(cap, bool) or not isinstance(cap, (float, int)) or not math.isfinite(cap) or cap <= 0):
            raise ValueError("max_minutes must be positive or null")
        destinations = person.get("destinations", [])
        if not isinstance(destinations, list) or not 1 <= len(destinations) <= 20:
            raise ValueError("Each person needs 1–20 destinations")
        dest_ids = set()
        for dest in destinations:
            if (not isinstance(dest, dict) or not isinstance(dest.get("id"), str)
                    or not dest["id"].strip() or dest["id"] != dest["id"].strip()
                    or dest["id"] in dest_ids):
                raise ValueError("Each destination needs a unique id within its person")
            dest_ids.add(dest["id"])
            for key, lower, upper in (("lat", -90, 90), ("lon", -180, 180), ("days_per_week", 0, 7)):
                value = dest.get(key)
                if (isinstance(value, bool) or not isinstance(value, (int, float))
                        or not math.isfinite(value) or not lower <= value <= upper):
                    raise ValueError(f"Destination {key} must be between {lower} and {upper}")
    sources = config.get("sources", [])
    if not isinstance(sources, list):
        raise ValueError("sources must be an array")
    source_ids = set()
    for source in sources:
        if (not isinstance(source, dict) or not isinstance(source.get("id"), str)
                or not source["id"].strip() or source["id"] != source["id"].strip()
                or source["id"] in source_ids):
            raise ValueError("Every source needs a unique id")
        source_ids.add(source["id"])
        adapter = source.get("adapter")
        from .collectors import SUPPORTED_ADAPTERS
        if adapter not in SUPPORTED_ADAPTERS:
            raise ValueError(f"Unsupported adapter: {adapter}")
        url = source.get("url")
        parsed = urlparse(url) if isinstance(url, str) else None
        if adapter != "homeharvest" and (not parsed or parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.username is not None):
            raise ValueError("Source URL must be an absolute HTTP(S) URL without credentials")
        enabled = source.get("enabled", False)
        if not isinstance(enabled, bool):
            raise ValueError("Source enabled must be true or false")
        note = source.get("permission_note")
        if note is not None and not isinstance(note, str):
            raise ValueError("Source permission_note must be text")
        if enabled and (not isinstance(note, str) or not note.strip()):
            raise ValueError("Enabled sources need a permission_note documenting your access basis")
    if not isinstance(config.get("routing", {}), dict):
        raise ValueError("routing must be an object")
    return config


def load_config(workspace):
    path = Path(workspace) / "config.json"
    if not path.exists():
        raise ValueError("Workspace is not initialized. Run goldblum init or goldblum demo first")
    return validate_config(json.loads(path.read_text()))


def save_config(workspace, config):
    validate_config(config)
    path = Path(workspace) / "config.json"
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(config, indent=2, allow_nan=False) + "\n")
    if os.name == "posix":
        os.chmod(temp, 0o600)
    temp.replace(path)


def default_config():
    return {"city": "Chicago", "timezone": "America/Chicago", "currency": "USD",
            "sources": [], "people": [], "routing": {}, "search": {}}
