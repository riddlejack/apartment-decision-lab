"""Search preferences are ordinary data; collection and filtering need no model."""
from datetime import date
import math


def validate_search(search):
    if not isinstance(search, dict):
        raise ValueError("search must be an object")
    for key in ("residents", "budget_per_person", "max_rent", "min_bedrooms", "min_bathrooms", "min_sqft"):
        value = search.get(key)
        if value in (None, ""):
            search[key] = None
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError(f"search.{key} must be a nonnegative number")
        if key == "residents" and (not 1 <= value <= 20 or int(value) != value):
            raise ValueError("Use 1–20 residents")
    if not search.get("max_rent") and search.get("residents") and search.get("budget_per_person"):
        search["max_rent"] = search["residents"] * search["budget_per_person"]
    for key in ("pets_required", "parking_required"):
        if key in search and not isinstance(search[key], bool):
            raise ValueError(f"search.{key} must be true or false")
    if search.get("move_in_date"):
        try:
            date.fromisoformat(search["move_in_date"])
        except (ValueError, TypeError):
            raise ValueError("move_in_date must be YYYY-MM-DD") from None
    return search


def assess(row, search):
    excluded, unknown = [], []
    checks = (("rent", "max_rent", lambda x, y: x <= y),
              ("bedrooms", "min_bedrooms", lambda x, y: x >= y),
              ("bathrooms", "min_bathrooms", lambda x, y: x >= y),
              ("sqft", "min_sqft", lambda x, y: x >= y))
    for field, setting, comparison in checks:
        bound = search.get(setting)
        if bound is None:
            continue
        if row.get(field) is None:
            unknown.append(field)
        elif not comparison(row[field], bound):
            excluded.append(field)
    for field, setting in (("pets", "pets_required"), ("parking", "parking_required")):
        if search.get(setting):
            if row.get(field) is None:
                unknown.append(field)
            elif not row[field]:
                excluded.append(field)
    if search.get("move_in_date"):
        try:
            available = date.fromisoformat(row.get("available_date") or "")
            if available > date.fromisoformat(search["move_in_date"]):
                excluded.append("available_date")
        except ValueError:
            unknown.append("available_date")
    return {"eligible": not excluded, "excluded": excluded, "needs_check": unknown}


def summarize(rows, search):
    values = [assess(row, search) for row in rows]
    return {"total": len(rows), "matching": sum(v["eligible"] for v in values),
            "needs_check": sum(v["eligible"] and bool(v["needs_check"]) for v in values),
            "excluded": sum(not v["eligible"] for v in values)}
