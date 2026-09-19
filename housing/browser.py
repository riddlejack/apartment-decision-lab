"""Emit the packaged DOM reader for an agent's existing browser session."""

import json
from importlib.resources import files

RECIPES = ("domu", "compass", "apartments", "zillow", "apartmentlist", "rentcafe", "generic")


def extraction_script(source, recipe="generic", search_url=None, options=None):
    if recipe not in RECIPES:
        raise ValueError(f"Unknown browser recipe: {recipe}")
    if not isinstance(source, str) or not source.strip():
        raise ValueError("A source id is required")
    if options is not None and not isinstance(options, dict):
        raise ValueError("Browser options must be a JSON object")
    settings = dict(options or {})
    settings.update(source=source, recipe=recipe)
    if search_url:
        settings["search_url"] = search_url
    # Saved preferences do not prove which filters were applied on the website.
    settings.setdefault("criteria", {})
    reader = files("housing").joinpath("browser_capture.js").read_text(encoding="utf-8").strip()
    return "() => (" + reader + ")(" + json.dumps(settings, allow_nan=False) + ")"
