"""Explicit, cached address geocoding through the official US Census API."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
from urllib import error, parse, request


PROVIDER = "US Census"
BENCHMARK = "Public_AR_Current"
ENDPOINT = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
TIMEOUT_SECONDS = 20
MAX_RESPONSE_BYTES = 1024 * 1024
USER_AGENT = "apartment-decision-lab/0.1 (explicit local geocode)"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _coordinate(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RuntimeError(f"US Census response has invalid {name}")
    number = float(value)
    if not math.isfinite(number):
        raise RuntimeError(f"US Census response has invalid {name}")
    return number


def _validated_matches(value: object) -> list[dict]:
    if not isinstance(value, list):
        raise RuntimeError("US Census response is missing address matches")
    matches: list[dict] = []
    for item in value:
        if not isinstance(item, dict) or not isinstance(item.get("address"), str) or not item["address"].strip():
            raise RuntimeError("US Census response has an invalid matched address")
        lat = _coordinate(item.get("lat"), "latitude")
        lon = _coordinate(item.get("lon"), "longitude")
        if not -90 <= lat <= 90 or not -180 <= lon <= 180 or (lat == 0 and lon == 0):
            raise RuntimeError("US Census response has invalid coordinates")
        matches.append({"address": item["address"].strip(), "lat": lat, "lon": lon})
    return matches


def _read_cache(path: Path, now: datetime) -> dict | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        fetched_at = datetime.fromisoformat(payload["fetched_at"].replace("Z", "+00:00"))
        if fetched_at.tzinfo is None or payload.get("provider") != PROVIDER or payload.get("benchmark") != BENCHMARK:
            return None
        matches = _validated_matches(payload.get("matches"))
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError, RuntimeError):
        return None
    age = max(0, int((now - fetched_at.astimezone(timezone.utc)).total_seconds()))
    return {
        "matches": matches,
        "provider": PROVIDER,
        "benchmark": BENCHMARK,
        "cached": True,
        "fetched_at": _timestamp(fetched_at.astimezone(timezone.utc)),
        "cache_age_seconds": age,
    }


def _write_cache(path: Path, payload: dict) -> None:
    fd, temporary = tempfile.mkstemp(prefix=f".{path.stem}-", suffix=".tmp", dir=path.parent)
    try:
        # fchmod is unavailable on Windows; its temp directory ACL remains the
        # effective protection there. Unix gets an explicit owner-only file.
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"), allow_nan=False)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def geocode_address(address: str, cache_dir: Path) -> dict:
    """Geocode one explicitly submitted US address, using a private local cache."""

    if not isinstance(address, str):
        raise ValueError("address must be a string")
    normalized = address.strip()
    if not normalized:
        raise ValueError("address is required")
    if len(normalized) > 500:
        raise ValueError("address must be 500 characters or fewer")

    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    cache_key = hashlib.sha256(f"{BENCHMARK}\0{normalized}".encode("utf-8")).hexdigest()
    cache_path = cache_dir / f"census-{cache_key}.json"
    now = _now()
    if cache_path.is_file():
        cached = _read_cache(cache_path, now)
        if cached is not None:
            return cached

    query = parse.urlencode({"address": normalized, "benchmark": BENCHMARK, "format": "json"})
    req = request.Request(f"{ENDPOINT}?{query}", headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with request.urlopen(req, timeout=TIMEOUT_SECONDS) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
    except error.HTTPError as exc:
        raise RuntimeError(f"US Census geocoder request failed with HTTP {exc.code}") from None
    except (error.URLError, TimeoutError, OSError):
        raise RuntimeError("US Census geocoder request failed") from None
    if len(body) > MAX_RESPONSE_BYTES:
        raise RuntimeError("US Census geocoder response exceeded 1 MiB")

    try:
        document = json.loads(body)
        raw_matches = document["result"]["addressMatches"]
        if not isinstance(raw_matches, list):
            raise TypeError
        converted = []
        for item in raw_matches:
            if not isinstance(item, dict):
                raise TypeError
            coordinates = item.get("coordinates")
            converted.append({
                "address": item.get("matchedAddress"),
                "lat": coordinates.get("y") if isinstance(coordinates, dict) else None,
                "lon": coordinates.get("x") if isinstance(coordinates, dict) else None,
            })
        matches = _validated_matches(converted)
    except (json.JSONDecodeError, KeyError, TypeError):
        raise RuntimeError("US Census geocoder returned an invalid response") from None

    fetched_at = _timestamp(_now())
    payload = {
        "matches": matches,
        "provider": PROVIDER,
        "benchmark": BENCHMARK,
        "fetched_at": fetched_at,
    }
    try:
        _write_cache(cache_path, payload)
    except OSError:
        raise RuntimeError("US Census geocode succeeded but its local cache could not be written") from None
    return {**payload, "cached": False, "cache_age_seconds": None}


__all__ = ["geocode_address"]
