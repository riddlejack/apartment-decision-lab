"""Portable, local routing and commute ranking.

The Python layer validates configuration, limits work to requested scenarios,
and ranks only complete same-mode round trips.  Actual paths and transit times
come from R5 through the bundled ``r5r_runner.R`` subprocess.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from copy import deepcopy
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


SCHEMA_VERSION = 2
ENGINE_ADAPTER_REVISION = 2
SUPPORTED_MODES = ("walk", "transit", "bike", "drive")
DEFAULT_ROUTING: dict[str, Any] = {
    "engine": "r5r",
    "date": None,
    "outbound_time": "08:00",
    "return_time": "17:30",
    "time_window_minutes": 10,
    "percentile": 50,
    "threads": 2,
    "max_memory_gb": 8,
    "max_trip_minutes": 120,
    "max_walk_minutes": 30,
    "walk_speed_kmh": 4.8,
    "bike_speed_kmh": 16.0,
    "max_lts": 2,
    "drive_enabled": False,
    "drive_parking_minutes": 0.0,
    "listing_ids": None,
    "max_origins": 1000,
    "cache": True,
    "timeout_seconds": 900,
}


class RoutingError(RuntimeError):
    """Raised when a real route computation cannot be completed safely."""


def _json_hash(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _routing_settings(config: dict[str, Any]) -> dict[str, Any]:
    routing = dict(DEFAULT_ROUTING)
    raw = config.get("routing") or {}
    if not isinstance(raw, dict):
        raise RoutingError("config.routing must be an object")
    routing.update(raw)
    return routing


def _canonical_config(config: dict[str, Any]) -> dict[str, Any]:
    """Return only configuration that can change routing or result mapping."""

    routing = _routing_settings(config)
    # Cache behavior, process timeout, and executable locations do not change
    # route values.  Local paths are represented in the separate network stamp.
    for key in ("cache", "timeout_seconds", "rscript", "java_home"):
        routing.pop(key, None)
    people: list[dict[str, Any]] = []
    for person in config.get("people") or []:
        people.append(
            {
                "id": person.get("id"),
                "modes": person.get("modes") or [],
                "destinations": [
                    {
                        "id": destination.get("id"),
                        "lat": destination.get("lat"),
                        "lon": destination.get("lon"),
                        "date": destination.get("date"),
                        "outbound_time": destination.get("outbound_time"),
                        "return_time": destination.get("return_time"),
                    }
                    for destination in (person.get("destinations") or [])
                ],
            }
        )
    return {
        "timezone": config.get("timezone"),
        "routing": routing,
        "people": people,
    }


def config_fingerprint(config: dict[str, Any]) -> str:
    """Fingerprint physical route inputs, excluding weights and caps."""

    return _json_hash(_canonical_config(config))


def _preference_fingerprint(config: dict[str, Any]) -> str:
    return _json_hash(
        [
            {
                "person_id": person.get("id"),
                "max_minutes": person.get("max_minutes"),
                "destinations": [
                    {
                        "id": destination.get("id"),
                        "days_per_week": destination.get("days_per_week", 1),
                    }
                    for destination in (person.get("destinations") or [])
                ],
            }
            for person in (config.get("people") or [])
        ]
    )


def _network_stamp(
    config: dict[str, Any], *, include_derived: bool = True
) -> dict[str, Any]:
    routing = _routing_settings(config)
    raw_path = routing.get("network_dir")
    if not raw_path:
        return {"network_dir": None, "files": []}
    network_dir = Path(str(raw_path)).expanduser().resolve()
    files: list[dict[str, Any]] = []
    for path in sorted(network_dir.glob("*")):
        source_input = path.suffix in {".zip", ".pbf"}
        derived_input = path.name in {"network.dat", "network_settings.json"}
        if not source_input and not (include_derived and derived_input):
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        record: dict[str, Any] = {
            "name": path.name,
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
        }
        if path.name == "network_settings.json":
            try:
                record["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                pass
        files.append(record)
    return {"network_dir": str(network_dir), "files": files}


def _source_hashes(network_dir: Path) -> dict[str, str]:
    """Hash immutable OSM/GTFS inputs once when producing a new payload."""

    hashes: dict[str, str] = {}
    for path in sorted(network_dir.iterdir()):
        if not path.is_file() or (path.suffix != ".pbf" and path.suffix != ".zip"):
            continue
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
        hashes[path.name] = digest.hexdigest()
    return hashes


def request_fingerprint(listings: Iterable[dict[str, Any]], config: dict[str, Any]) -> str:
    """Fingerprint all origin geometry, route configuration, and network files."""

    listing_rows = list(listings)
    selected_ids = _configured_listing_ids(config)
    origins = [
        {
            "id": listing.get("id"),
            "lat": listing.get("lat"),
            "lon": listing.get("lon"),
        }
        for listing in listing_rows
        if selected_ids is None or str(listing.get("id")) in selected_ids
    ]
    origins.sort(key=lambda item: str(item.get("id")))
    return _json_hash(
        {
            "schema_version": SCHEMA_VERSION,
            "engine_adapter_revision": ENGINE_ADAPTER_REVISION,
            "config_fingerprint": config_fingerprint(config),
            "origins": origins,
            # Derived network.dat/settings may be created on the first run.
            # Fingerprint source bytes only so cache identity stays stable.
            "network": _network_stamp(config, include_derived=False),
        }
    )


def routes_match(
    listings: Iterable[dict[str, Any]],
    config: dict[str, Any],
    payload: dict[str, Any] | None,
) -> bool:
    """Return whether a saved route payload is current for these inputs."""

    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        return False
    return payload.get("request_fingerprint") == request_fingerprint(listings, config)


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _coordinate(lat: Any, lon: Any) -> tuple[float, float] | None:
    latitude = _finite_number(lat)
    longitude = _finite_number(lon)
    if latitude is None or longitude is None:
        return None
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None
    return latitude, longitude


def _parse_date(value: Any, label: str) -> date:
    if not isinstance(value, str):
        raise RoutingError(f"{label} must be an ISO date (YYYY-MM-DD)")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise RoutingError(f"{label} must be an ISO date (YYYY-MM-DD)") from exc


_TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


def _parse_time(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _TIME_RE.fullmatch(value):
        raise RoutingError(f"{label} must use 24-hour HH:MM")
    return value


def _positive_int(value: Any, label: str, *, minimum: int = 1) -> int:
    if isinstance(value, bool):
        raise RoutingError(f"{label} must be an integer >= {minimum}")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise RoutingError(f"{label} must be an integer >= {minimum}") from exc
    if result != value or result < minimum:
        raise RoutingError(f"{label} must be an integer >= {minimum}")
    return result


def _configured_listing_ids(config: dict[str, Any]) -> set[str] | None:
    raw = _routing_settings(config).get("listing_ids")
    if raw is None:
        return None
    if not isinstance(raw, list) or not raw:
        raise RoutingError("config.routing.listing_ids must be a non-empty list when set")
    identifiers = [str(value).strip() for value in raw]
    if any(not value for value in identifiers) or len(set(identifiers)) != len(identifiers):
        raise RoutingError("config.routing.listing_ids must contain unique non-empty ids")
    return set(identifiers)


def _validate_settings(config: dict[str, Any], settings: dict[str, Any]) -> None:
    if settings.get("engine") != "r5r":
        raise RoutingError("config.routing.engine must be 'r5r'")
    network_dir = settings.get("network_dir")
    if not network_dir:
        raise RoutingError("config.routing.network_dir is required")
    if not Path(str(network_dir)).expanduser().is_dir():
        raise RoutingError(f"routing network directory does not exist: {network_dir}")
    timezone_name = config.get("timezone")
    if not isinstance(timezone_name, str) or not timezone_name:
        raise RoutingError("config.timezone is required")
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise RoutingError(f"unknown timezone: {timezone_name}") from exc
    _parse_date(settings.get("date"), "config.routing.date")
    _parse_time(settings.get("outbound_time"), "config.routing.outbound_time")
    _parse_time(settings.get("return_time"), "config.routing.return_time")
    _positive_int(settings.get("time_window_minutes"), "time_window_minutes")
    percentile = _positive_int(settings.get("percentile"), "percentile")
    if percentile > 100:
        raise RoutingError("percentile must be between 1 and 100")
    _positive_int(settings.get("threads"), "threads")
    _positive_int(settings.get("max_memory_gb"), "max_memory_gb")
    _positive_int(settings.get("max_origins"), "max_origins")
    _positive_int(settings.get("max_trip_minutes"), "max_trip_minutes")
    _positive_int(settings.get("max_walk_minutes"), "max_walk_minutes")
    max_lts = _positive_int(settings.get("max_lts"), "max_lts")
    if max_lts > 4:
        raise RoutingError("max_lts must be between 1 and 4")
    for key in ("walk_speed_kmh", "bike_speed_kmh"):
        value = _finite_number(settings.get(key))
        if value is None or value <= 0:
            raise RoutingError(f"{key} must be a positive number")
    parking = _finite_number(settings.get("drive_parking_minutes"))
    if parking is None or parking < 0:
        raise RoutingError("drive_parking_minutes must be a non-negative number")
    _configured_listing_ids(config)


def _validate_network_cache(network_dir: Path) -> None:
    """Refuse an R5 cache older than one of its OSM/GTFS source files."""

    cache = network_dir / "network.dat"
    if not cache.is_file():
        return
    cache_mtime = cache.stat().st_mtime_ns
    newer_sources = [
        path.name
        for path in network_dir.iterdir()
        if path.is_file()
        and (path.suffix == ".pbf" or path.suffix == ".zip")
        and path.stat().st_mtime_ns > cache_mtime
    ]
    if newer_sources:
        raise RoutingError(
            "cached R5 network predates source file(s): "
            + ", ".join(sorted(newer_sources))
            + "; rebuild the network cache before routing"
        )


def _normalized_people(
    config: dict[str, Any], settings: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    people_raw = config.get("people") or []
    if not isinstance(people_raw, list):
        raise RoutingError("config.people must be a list")
    people: list[dict[str, Any]] = []
    destinations: list[dict[str, Any]] = []
    person_ids: set[str] = set()
    for person_index, person in enumerate(people_raw):
        if not isinstance(person, dict):
            raise RoutingError("each person must be an object")
        person_id = str(person.get("id") or "").strip()
        if not person_id or person_id in person_ids:
            raise RoutingError("each person needs a unique non-empty id")
        person_ids.add(person_id)
        modes = []
        for raw_mode in person.get("modes") or []:
            mode = str(raw_mode).lower()
            if mode not in SUPPORTED_MODES:
                raise RoutingError(
                    f"unsupported mode {raw_mode!r} for person {person_id}; "
                    f"choose from {', '.join(SUPPORTED_MODES)}"
                )
            if mode not in modes:
                modes.append(mode)
        if not modes:
            raise RoutingError(f"person {person_id} needs at least one allowed mode")
        maximum = person.get("max_minutes")
        if maximum is not None:
            maximum = _finite_number(maximum)
            if maximum is None or maximum < 0:
                raise RoutingError(f"max_minutes for person {person_id} must be non-negative")
        person_destinations = person.get("destinations") or []
        if not isinstance(person_destinations, list) or not person_destinations:
            raise RoutingError(f"person {person_id} needs at least one destination")
        seen_destination_ids: set[str] = set()
        normalized_destination_ids: list[str] = []
        for destination_index, destination in enumerate(person_destinations):
            if not isinstance(destination, dict):
                raise RoutingError(f"destinations for person {person_id} must be objects")
            destination_id = str(destination.get("id") or "").strip()
            if not destination_id or destination_id in seen_destination_ids:
                raise RoutingError(
                    f"destinations for person {person_id} need unique non-empty ids"
                )
            seen_destination_ids.add(destination_id)
            days = _finite_number(destination.get("days_per_week", 1))
            if days is None or not (0 <= days <= 7):
                raise RoutingError(
                    f"days_per_week for {person_id}/{destination_id} must be between 0 and 7"
                )
            route_key = f"d{person_index:04d}_{destination_index:04d}"
            route_date = _parse_date(
                destination.get("date") or settings["date"],
                f"date for {person_id}/{destination_id}",
            ).isoformat()
            outbound_time = _parse_time(
                destination.get("outbound_time") or settings["outbound_time"],
                f"outbound_time for {person_id}/{destination_id}",
            )
            return_time = _parse_time(
                destination.get("return_time") or settings["return_time"],
                f"return_time for {person_id}/{destination_id}",
            )
            destinations.append(
                {
                    "route_key": route_key,
                    "person_id": person_id,
                    "id": destination_id,
                    "name": destination.get("name") or destination_id,
                    "lat": destination.get("lat"),
                    "lon": destination.get("lon"),
                    "coordinate": _coordinate(destination.get("lat"), destination.get("lon")),
                    "days_per_week": days,
                    "date": route_date,
                    "outbound_time": outbound_time,
                    "return_time": return_time,
                }
            )
            normalized_destination_ids.append(destination_id)
        people.append(
            {
                "id": person_id,
                "name": person.get("name") or person_id,
                "modes": modes,
                "max_minutes": maximum,
                "destination_ids": normalized_destination_ids,
            }
        )
    if not people:
        raise RoutingError("config.people must contain at least one person")
    return people, destinations


def _read_gtfs_rows(archive: zipfile.ZipFile, member: str) -> list[dict[str, str]]:
    try:
        raw = archive.read(member)
    except KeyError:
        return []
    text = raw.decode("utf-8-sig", errors="replace")
    return list(csv.DictReader(text.splitlines(), skipinitialspace=True))


def _gtfs_date(raw: str | None) -> date | None:
    if not raw:
        return None
    try:
        return datetime.strptime(raw.strip(), "%Y%m%d").date()
    except ValueError:
        return None


def _inspect_gtfs_feed(path: Path, requested_dates: set[date]) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(path) as archive:
            calendar = _read_gtfs_rows(archive, "calendar.txt")
            exceptions = _read_gtfs_rows(archive, "calendar_dates.txt")
            feed_info = _read_gtfs_rows(archive, "feed_info.txt")
    except (OSError, zipfile.BadZipFile) as exc:
        raise RoutingError(f"cannot read GTFS archive {path.name}: {exc}") from exc

    starts = [_gtfs_date(row.get("start_date")) for row in calendar]
    ends = [_gtfs_date(row.get("end_date")) for row in calendar]
    exception_dates = [_gtfs_date(row.get("date")) for row in exceptions]
    start_candidates = [value for value in starts + exception_dates if value]
    end_candidates = [value for value in ends + exception_dates if value]
    coverage_start = min(start_candidates) if start_candidates else None
    coverage_end = max(end_candidates) if end_candidates else None

    exception_by_date: dict[date, list[dict[str, str]]] = {}
    for row in exceptions:
        parsed = _gtfs_date(row.get("date"))
        if parsed:
            exception_by_date.setdefault(parsed, []).append(row)
    weekdays = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
    active_by_date: dict[str, int] = {}
    for requested in sorted(requested_dates):
        active: set[str] = set()
        weekday = weekdays[requested.weekday()]
        for row in calendar:
            start = _gtfs_date(row.get("start_date"))
            end = _gtfs_date(row.get("end_date"))
            if start and end and start <= requested <= end and row.get(weekday, "").strip() == "1":
                active.add(row.get("service_id", "").strip())
        for row in exception_by_date.get(requested, []):
            service_id = row.get("service_id", "").strip()
            if row.get("exception_type", "").strip() == "1":
                active.add(service_id)
            elif row.get("exception_type", "").strip() == "2":
                active.discard(service_id)
        active_by_date[requested.isoformat()] = len(active)

    info = feed_info[0] if feed_info else {}
    return {
        "file": path.name,
        "publisher": info.get("feed_publisher_name") or None,
        "version": info.get("feed_version") or None,
        "coverage_start": coverage_start.isoformat() if coverage_start else None,
        "coverage_end": coverage_end.isoformat() if coverage_end else None,
        "active_services": active_by_date,
        "coverage_known": coverage_start is not None and coverage_end is not None,
        "dates_in_range": {
            requested.isoformat(): bool(
                coverage_start and coverage_end and coverage_start <= requested <= coverage_end
            )
            for requested in sorted(requested_dates)
        },
    }


def _validate_gtfs_dates(network_dir: Path, requested_dates: set[date]) -> list[dict[str, Any]]:
    feeds = [_inspect_gtfs_feed(path, requested_dates) for path in sorted(network_dir.glob("*.zip"))]
    if not feeds:
        raise RoutingError("transit was requested but network_dir contains no GTFS .zip feeds")
    unknown = [feed["file"] for feed in feeds if not feed["coverage_known"]]
    if unknown:
        raise RoutingError(
            "cannot verify requested transit dates for GTFS feed(s): " + ", ".join(unknown)
        )
    outside = [
        f"{feed['file']} ({day})"
        for feed in feeds
        for day, valid in feed["dates_in_range"].items()
        if not valid
    ]
    if outside:
        raise RoutingError(
            "requested transit date is outside GTFS calendar coverage: " + ", ".join(outside)
        )
    return feeds


def _java_home(settings: dict[str, Any]) -> str | None:
    candidates: list[Path] = []
    if settings.get("java_home"):
        candidates.append(Path(str(settings["java_home"])).expanduser())
    if os.environ.get("JAVA_HOME"):
        candidates.append(Path(os.environ["JAVA_HOME"]).expanduser())
    candidates.extend(
        [
            Path("/opt/homebrew/opt/openjdk@21"),
            Path("/opt/homebrew/opt/openjdk"),
            Path("/usr/local/opt/openjdk@21"),
            Path("/usr/local/opt/openjdk"),
        ]
    )
    for candidate in candidates:
        variants = (candidate, candidate / "libexec/openjdk.jdk/Contents/Home")
        for variant in variants:
            if (variant / "bin/java").is_file() and (variant / "lib/server").is_dir():
                return str(variant.resolve())
    java_home_tool = Path("/usr/libexec/java_home")
    if java_home_tool.is_file():
        result = subprocess.run(
            [str(java_home_tool)], capture_output=True, text=True, check=False
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    return None


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _normalize_engine_orientation(
    rows: list[dict[str, str]],
    jobs: list[dict[str, Any]],
    origin_ids: set[str],
) -> list[dict[str, str]]:
    """Correct a known r5r 2.4 direct-WALK id-column reversal when observed.

    The correction is evidence-based per job: rows are swapped only when more
    rows match the exact reverse of that job's requested point-set orientation
    than match the requested orientation. Correctly oriented modes and future
    engine versions pass through unchanged.
    """

    jobs_by_id = {job["job_id"]: job for job in jobs}
    grouped: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        grouped.setdefault(row.get("job_id", ""), []).append(dict(row))
    normalized: list[dict[str, str]] = []
    for job_id, job_rows in grouped.items():
        job = jobs_by_id.get(job_id)
        if job is None:
            raise RoutingError(f"r5r returned an unknown job id: {job_id}")
        destination_ids = set(str(job["destination_keys"]).split(";"))
        if job["direction"] == "outbound":
            expected_from, expected_to = origin_ids, destination_ids
        else:
            expected_from, expected_to = destination_ids, origin_ids
        forward = sum(
            row.get("from_id") in expected_from and row.get("to_id") in expected_to
            for row in job_rows
        )
        reverse = sum(
            row.get("from_id") in expected_to and row.get("to_id") in expected_from
            for row in job_rows
        )
        if reverse > forward:
            for row in job_rows:
                row["from_id"], row["to_id"] = row["to_id"], row["from_id"]
        normalized.extend(job_rows)
    return normalized


def _execute_r5r(
    *,
    origins: list[dict[str, Any]],
    destinations: list[dict[str, Any]],
    jobs: list[dict[str, Any]],
    config: dict[str, Any],
    settings: dict[str, Any],
    output_dir: Path,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Run all bounded matrices in one JVM and return normalized CSV rows."""

    runner = Path(__file__).with_name("r5r_runner.R")
    if not runner.is_file():
        raise RoutingError(f"bundled r5r runner is missing: {runner}")
    rscript = str(settings.get("rscript") or shutil.which("Rscript") or "")
    if not rscript:
        raise RoutingError("Rscript is required for routing but was not found")

    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="housing-r5r-", dir=output_dir) as temp_name:
        temp = Path(temp_name)
        origins_path = temp / "origins.csv"
        destinations_path = temp / "destinations.csv"
        jobs_path = temp / "jobs.csv"
        results_path = temp / "results.csv"
        metadata_path = temp / "metadata.csv"
        _write_csv(origins_path, origins, ["id", "lat", "lon"])
        _write_csv(destinations_path, destinations, ["id", "lat", "lon"])
        _write_csv(
            jobs_path,
            jobs,
            ["job_id", "direction", "mode", "departure", "destination_keys"],
        )
        command = [
            rscript,
            str(runner),
            "--network-dir",
            str(Path(str(settings["network_dir"])).expanduser().resolve()),
            "--origins",
            str(origins_path),
            "--destinations",
            str(destinations_path),
            "--jobs",
            str(jobs_path),
            "--output",
            str(results_path),
            "--metadata",
            str(metadata_path),
            "--timezone",
            str(config["timezone"]),
            "--threads",
            str(settings["threads"]),
            "--memory-gb",
            str(settings["max_memory_gb"]),
            "--time-window",
            str(settings["time_window_minutes"]),
            "--percentile",
            str(settings["percentile"]),
            "--max-trip",
            str(settings["max_trip_minutes"]),
            "--max-walk",
            str(settings["max_walk_minutes"]),
            "--walk-speed",
            str(settings["walk_speed_kmh"]),
            "--bike-speed",
            str(settings["bike_speed_kmh"]),
            "--max-lts",
            str(settings["max_lts"]),
        ]
        environment = os.environ.copy()
        java_home = _java_home(settings)
        if java_home:
            environment["JAVA_HOME"] = java_home
            environment["PATH"] = str(Path(java_home) / "bin") + os.pathsep + environment.get("PATH", "")
        try:
            process = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=int(settings["timeout_seconds"]),
                env=environment,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RoutingError(
                f"r5r exceeded the configured {settings['timeout_seconds']} second timeout"
            ) from exc
        if process.returncode != 0:
            detail = (process.stderr or process.stdout or "unknown r5r error").strip().splitlines()
            raise RoutingError("r5r failed: " + " | ".join(detail[-8:]))

        rows: list[dict[str, str]] = []
        if results_path.is_file() and results_path.stat().st_size:
            with results_path.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
        rows = _normalize_engine_orientation(
            rows, jobs, {str(origin["id"]) for origin in origins}
        )
        metadata: dict[str, Any] = {}
        if metadata_path.is_file() and metadata_path.stat().st_size:
            with metadata_path.open(encoding="utf-8", newline="") as handle:
                metadata_rows = list(csv.DictReader(handle))
            if metadata_rows:
                metadata = metadata_rows[0]
        metadata["java_home"] = java_home
        return rows, metadata


def _build_jobs(
    destinations: list[dict[str, Any]], modes_to_compute: set[str]
) -> tuple[list[dict[str, Any]], dict[tuple[str, str, str, str], str]]:
    scenario_destinations: dict[tuple[str, str, str, str], list[str]] = {}
    for destination in destinations:
        if not destination["coordinate"]:
            continue
        for mode in sorted(modes_to_compute):
            for direction, time_key in (
                ("outbound", "outbound_time"),
                ("return", "return_time"),
            ):
                key = (direction, mode, destination["date"], destination[time_key])
                scenario_destinations.setdefault(key, []).append(destination["route_key"])
    jobs: list[dict[str, Any]] = []
    job_lookup: dict[tuple[str, str, str, str], str] = {}
    for index, (key, destination_keys) in enumerate(sorted(scenario_destinations.items())):
        direction, mode, day, clock = key
        job_id = f"j{index:04d}"
        jobs.append(
            {
                "job_id": job_id,
                "direction": direction,
                "mode": mode,
                "departure": f"{day} {clock}:00",
                "destination_keys": ";".join(destination_keys),
            }
        )
        job_lookup[key] = job_id
    return jobs, job_lookup


def _round_minutes(value: float | None) -> float | None:
    return None if value is None else round(value, 2)


def _refresh_preferences(
    payload: dict[str, Any],
    people: list[dict[str, Any]],
    destinations: list[dict[str, Any]],
    config: dict[str, Any],
) -> None:
    """Refresh cheap weights/caps without invalidating physical route geometry."""

    person_by_id = {person["id"]: person for person in people}
    destination_by_id = {
        (destination["person_id"], destination["id"]): destination
        for destination in destinations
    }
    for result in payload.get("results", []):
        person = person_by_id.get(result.get("person_id"))
        destination = destination_by_id.get(
            (result.get("person_id"), result.get("destination_id"))
        )
        if person is None or destination is None:
            continue
        daily = (
            float(result["outbound_minutes"]) + float(result["return_minutes"])
            if result.get("roundtrip_valid")
            else None
        )
        maximum = person["max_minutes"]
        result["days_per_week"] = destination["days_per_week"]
        result["daily_minutes"] = _round_minutes(daily)
        result["weekly_minutes"] = _round_minutes(daily * destination["days_per_week"] if daily is not None else None)
        result["max_minutes"] = maximum
        result["capped"] = bool(
            daily is not None
            and maximum is not None
            and max(float(result["outbound_minutes"]), float(result["return_minutes"])) > maximum
        )
    scenario_by_id = {
        (destination["person_id"], destination["id"]): destination
        for destination in destinations
    }
    for scenario in payload.get("scenarios", []):
        destination = scenario_by_id.get(
            (scenario.get("person_id"), scenario.get("destination_id"))
        )
        if destination:
            scenario["days_per_week"] = destination["days_per_week"]
    payload["preference_fingerprint"] = _preference_fingerprint(config)


def _origin_matrix(origins, destinations, jobs, config, settings, output_dir):
    """Cache matrix rows by coordinates, preserving distinct listing identities."""
    canonical = _canonical_config(config)
    canonical["routing"].pop("listing_ids", None)
    canonical["routing"].pop("max_origins", None)
    context = {"config": canonical, "network": _network_stamp(config, include_derived=False),
               "adapter": ENGINE_ADAPTER_REVISION, "jobs": jobs}
    groups = {}
    for origin in origins:
        point_id = "point-" + _json_hash([origin["lat"], origin["lon"]])[:24]
        groups.setdefault(point_id, []).append(origin)
    folder = output_dir / "points"
    cached, paths, pending = {}, {}, []
    for point_id, entries in groups.items():
        point = {**entries[0], "id": point_id}
        key = _json_hash({"context": context, "point": point})
        paths[point_id] = folder / f"{key}.json"
        if settings.get("cache") and paths[point_id].is_file():
            try:
                value = json.loads(paths[point_id].read_text())
                if value.get("key") == key and isinstance(value.get("rows"), list):
                    cached[point_id] = value
                    continue
            except (OSError, ValueError, AttributeError):
                pass
        pending.append(point)
    metadata = next(iter(cached.values()), {}).get("metadata", {})
    if pending:
        rows, metadata = _execute_r5r(origins=pending, destinations=destinations, jobs=jobs,
                                     config=config, settings=settings, output_dir=output_dir)
        by_point = {point["id"]: [] for point in pending}
        for row in rows:
            point_id = row["from_id"] if row["direction"] == "outbound" else row["to_id"]
            if point_id in by_point:
                by_point[point_id].append(row)
        for point in pending:
            point_id = point["id"]
            value = {"key": paths[point_id].stem, "rows": by_point[point_id], "metadata": metadata}
            cached[point_id] = value
            if settings.get("cache"):
                folder.mkdir(parents=True, exist_ok=True, mode=0o700)
                temporary = paths[point_id].with_suffix(".tmp")
                temporary.write_text(json.dumps(value, allow_nan=False))
                temporary.replace(paths[point_id])
    expanded = []
    for point_id, entries in groups.items():
        for origin in entries:
            for raw in cached[point_id]["rows"]:
                row = dict(raw)
                row["from_id" if row["direction"] == "outbound" else "to_id"] = origin["id"]
                expanded.append(row)
    return expanded, {**metadata, "unique_origins": len(groups), "origins_computed": len(pending),
                       "origins_reused": len(groups) - len(pending)}


def compute_routes(
    listings: Iterable[dict[str, Any]],
    config: dict[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    """Compute requested OSM/GTFS routes with a local r5r engine.

    One result is returned for every listing/person/destination/allowed-mode
    combination, including combinations whose route is unavailable.  Missing
    values are JSON null and never zero.
    """

    listing_rows = list(listings)
    listing_ids: set[str] = set()
    normalized_listings: list[dict[str, Any]] = []
    for listing in listing_rows:
        listing_id = str(listing.get("id") or "").strip()
        if not listing_id or listing_id in listing_ids:
            raise RoutingError("listings need unique non-empty ids")
        listing_ids.add(listing_id)
        normalized_listings.append(
            {
                "id": listing_id,
                "lat": listing.get("lat"),
                "lon": listing.get("lon"),
                "coordinate": _coordinate(listing.get("lat"), listing.get("lon")),
            }
        )
    settings = _routing_settings(config)
    _validate_settings(config, settings)
    network_dir = Path(str(settings["network_dir"])).expanduser().resolve()
    _validate_network_cache(network_dir)
    people, destinations = _normalized_people(config, settings)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    selected_ids = _configured_listing_ids(config)
    if selected_ids is not None:
        missing_ids = selected_ids - listing_ids
        if missing_ids:
            raise RoutingError(
                "config.routing.listing_ids not found in listings: "
                + ", ".join(sorted(missing_ids))
            )
        scoped_listings = [row for row in normalized_listings if row["id"] in selected_ids]
    else:
        scoped_listings = normalized_listings
    max_origins = int(settings["max_origins"])
    if len(scoped_listings) > max_origins:
        raise RoutingError(
            f"routing request has {len(scoped_listings)} origins, above max_origins={max_origins}; "
            "set config.routing.listing_ids to the shortlist or explicitly raise max_origins"
        )

    fingerprint = request_fingerprint(listing_rows, config)
    cache_path = output_dir / "cache" / f"{fingerprint}.json"
    if bool(settings.get("cache")) and cache_path.is_file():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cached = None
        if routes_match(listing_rows, config, cached):
            payload = deepcopy(cached)
            _refresh_preferences(payload, people, destinations, config)
            payload["cache"] = {"hit": True, "key": fingerprint}
            return payload

    requested_modes = {mode for person in people for mode in person["modes"]}
    modes_to_compute = set(requested_modes)
    if "drive" in modes_to_compute and not bool(settings.get("drive_enabled")):
        modes_to_compute.remove("drive")
    valid_origins = [
        {"id": listing["id"], "lat": listing["coordinate"][0], "lon": listing["coordinate"][1]}
        for listing in scoped_listings
        if listing["coordinate"]
    ]
    valid_destinations = [
        {"id": destination["route_key"], "lat": destination["coordinate"][0], "lon": destination["coordinate"][1]}
        for destination in destinations
        if destination["coordinate"]
    ]
    jobs, job_lookup = _build_jobs(destinations, modes_to_compute)

    requested_dates = {
        _parse_date(destination["date"], "destination date")
        for destination in destinations
    }
    gtfs_feeds: list[dict[str, Any]] = []
    if "transit" in modes_to_compute:
        gtfs_feeds = _validate_gtfs_dates(
            network_dir, requested_dates
        )

    matrix_rows: list[dict[str, str]] = []
    engine_metadata: dict[str, Any] = {}
    if valid_origins and valid_destinations and jobs:
        matrix_rows, engine_metadata = _origin_matrix(
            origins=valid_origins,
            destinations=valid_destinations,
            jobs=jobs,
            config=config,
            settings=settings,
            output_dir=output_dir,
        )

    times: dict[tuple[str, str, str, str], float] = {}
    for row in matrix_rows:
        value = _finite_number(row.get("minutes"))
        if value is None or value < 0:
            continue
        times[(row["job_id"], row["direction"], row["from_id"], row["to_id"])] = value

    person_by_id = {person["id"]: person for person in people}
    results: list[dict[str, Any]] = []
    parking = float(settings["drive_parking_minutes"])
    for listing in scoped_listings:
        for destination in destinations:
            person = person_by_id[destination["person_id"]]
            for mode in person["modes"]:
                outbound: float | None = None
                returned: float | None = None
                reason: str | None = None
                if not listing["coordinate"]:
                    reason = "listing_coordinates_missing"
                elif not destination["coordinate"]:
                    reason = "destination_coordinates_missing"
                elif mode == "drive" and not bool(settings.get("drive_enabled")):
                    reason = "drive_requires_explicit_opt_in"
                else:
                    outbound_key = (
                        "outbound",
                        mode,
                        destination["date"],
                        destination["outbound_time"],
                    )
                    return_key = (
                        "return",
                        mode,
                        destination["date"],
                        destination["return_time"],
                    )
                    outbound_job = job_lookup[outbound_key]
                    return_job = job_lookup[return_key]
                    outbound = times.get(
                        (outbound_job, "outbound", listing["id"], destination["route_key"])
                    )
                    returned = times.get(
                        (return_job, "return", destination["route_key"], listing["id"])
                    )
                    if mode == "drive":
                        if outbound is not None:
                            outbound += parking
                        if returned is not None:
                            returned += parking
                    if outbound is None and returned is None:
                        reason = "route_not_found"
                    elif outbound is None:
                        reason = "outbound_route_not_found"
                    elif returned is None:
                        reason = "return_route_not_found"

                roundtrip_valid = outbound is not None and returned is not None
                daily = outbound + returned if roundtrip_valid else None
                weekly = daily * destination["days_per_week"] if daily is not None else None
                result = {
                    "listing_id": listing["id"],
                    "person_id": destination["person_id"],
                    "destination_id": destination["id"],
                    "mode": mode,
                    "model": (
                        "free_flow_osm_plus_parking"
                        if mode == "drive"
                        else "r5_walk_transit"
                        if mode == "transit"
                        else "osm_network"
                    ),
                    "date": destination["date"],
                    "outbound_time": destination["outbound_time"],
                    "return_time": destination["return_time"],
                    "outbound_minutes": _round_minutes(outbound),
                    "return_minutes": _round_minutes(returned),
                    "outbound_available": outbound is not None,
                    "return_available": returned is not None,
                    "available": roundtrip_valid,
                    "roundtrip_valid": roundtrip_valid,
                    "unavailable_reason": reason,
                    "days_per_week": destination["days_per_week"],
                    "daily_minutes": _round_minutes(daily),
                    "weekly_minutes": _round_minutes(weekly),
                    "max_minutes": person["max_minutes"],
                    "capped": bool(
                        roundtrip_valid
                        and person["max_minutes"] is not None
                        and max(outbound, returned) > person["max_minutes"]
                    ),
                    "percentile": settings["percentile"],
                    "time_window_minutes": settings["time_window_minutes"] if mode == "transit" else 1,
                    "parking_minutes_per_leg": parking if mode == "drive" else 0,
                }
                results.append(result)

    missing_count = sum(not result["roundtrip_valid"] for result in results)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "success" if missing_count == 0 else "partial",
        "config_fingerprint": config_fingerprint(config),
        "preference_fingerprint": _preference_fingerprint(config),
        "request_fingerprint": fingerprint,
        "cache": {"hit": False, "key": fingerprint},
        "engine": {
            "name": "R5 via r5r",
            "method": "local_osm_gtfs",
            "metadata": engine_metadata,
        },
        "provenance": {
            "timezone": config["timezone"],
            "network": _network_stamp(config),
            "source_sha256": _source_hashes(network_dir),
            "gtfs_feeds": gtfs_feeds,
            "route_models": {
                "walk": "OSM street network",
                "bike": f"OSM street network, maximum LTS {settings['max_lts']}",
                "transit": "R5 walk plus scheduled-transit option with walking access and egress",
                "drive": "OSM/R5 free-flow time; no traffic; parking overhead added per leg",
            },
            "park_and_ride": "not_implemented",
        },
        "scenarios": [
            {
                "person_id": destination["person_id"],
                "destination_id": destination["id"],
                "date": destination["date"],
                "outbound_time": destination["outbound_time"],
                "return_time": destination["return_time"],
                "days_per_week": destination["days_per_week"],
            }
            for destination in destinations
        ],
        "results": results,
        "summary": {
            "result_count": len(results),
            "available_roundtrips": len(results) - missing_count,
            "unavailable_roundtrips": missing_count,
            "origin_count": len(scoped_listings),
            "excluded_origin_count": len(normalized_listings) - len(scoped_listings),
        },
    }
    if bool(settings.get("cache")):
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def rank_listings(
    listings: Iterable[dict[str, Any]],
    people: Iterable[dict[str, Any]],
    route_payload: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Rank listings from complete, same-mode round trips.

    For each destination, the fastest allowed mode with both directional legs
    is selected.  ``days_per_week`` weights weekly totals. ``max_minutes`` is
    a one-way cap and is compared with the worst selected directional leg.
    """

    results = route_payload.get("results", []) if isinstance(route_payload, dict) else []
    route_index: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for result in results:
        if not isinstance(result, dict):
            continue
        key = (
            str(result.get("listing_id")),
            str(result.get("person_id")),
            str(result.get("destination_id")),
        )
        route_index.setdefault(key, []).append(result)

    people_rows = list(people)
    rankings: list[dict[str, Any]] = []
    for listing in listings:
        listing_id = str(listing.get("id"))
        person_summaries: list[dict[str, Any]] = []
        missing_routes: list[dict[str, str]] = []
        for person in people_rows:
            person_id = str(person.get("id"))
            allowed_modes = [str(mode).lower() for mode in (person.get("modes") or [])]
            mode_order = {mode: index for index, mode in enumerate(allowed_modes)}
            maximum = _finite_number(person.get("max_minutes"))
            destination_summaries: list[dict[str, Any]] = []
            total_weekly = 0.0
            total_days = 0.0
            worst_leg = 0.0
            complete = True
            for destination in person.get("destinations") or []:
                destination_id = str(destination.get("id"))
                days = _finite_number(destination.get("days_per_week", 1))
                days = days if days is not None and days >= 0 else 0.0
                if days == 0:
                    destination_summaries.append(
                        {
                            "destination_id": destination_id,
                            "complete": True,
                            "ignored_zero_weight": True,
                            "best_mode": None,
                            "outbound_mode": None,
                            "return_mode": None,
                            "outbound_minutes": None,
                            "return_minutes": None,
                            "daily_minutes": 0.0,
                            "weekly_minutes": 0.0,
                            "days_per_week": 0.0,
                        }
                    )
                    continue
                route_rows = route_index.get((listing_id, person_id, destination_id), [])
                candidates: list[dict[str, Any]] = []
                # A personal bicycle or car must be used in both directions so
                # it is available for the return. Walk and transit have no such
                # custody constraint and can be selected independently by leg.
                for result in route_rows:
                    mode = str(result.get("mode", "")).lower()
                    outbound = _finite_number(result.get("outbound_minutes"))
                    returned = _finite_number(result.get("return_minutes"))
                    if (
                        mode in {"bike", "drive"}
                        and mode in mode_order
                        and result.get("roundtrip_valid") is True
                        and outbound is not None
                        and returned is not None
                    ):
                        candidates.append(
                            {
                                "outbound_mode": mode,
                                "return_mode": mode,
                                "_outbound": outbound,
                                "_return": returned,
                                "_daily": outbound + returned,
                            }
                        )
                flexible = {"walk", "transit"}.intersection(mode_order)
                outbound_options: list[tuple[str, float]] = []
                return_options: list[tuple[str, float]] = []
                for result in route_rows:
                    mode = str(result.get("mode", "")).lower()
                    if mode not in flexible:
                        continue
                    outbound = _finite_number(result.get("outbound_minutes"))
                    returned = _finite_number(result.get("return_minutes"))
                    if outbound is not None:
                        outbound_options.append((mode, outbound))
                    if returned is not None:
                        return_options.append((mode, returned))
                for outbound_mode, outbound in outbound_options:
                    for return_mode, returned in return_options:
                        candidates.append(
                            {
                                "outbound_mode": outbound_mode,
                                "return_mode": return_mode,
                                "_outbound": outbound,
                                "_return": returned,
                                "_daily": outbound + returned,
                            }
                        )
                if not candidates:
                    complete = False
                    missing_routes.append(
                        {
                            "person_id": person_id,
                            "destination_id": destination_id,
                            "reason": "no_valid_roundtrip_with_allowed_modes",
                        }
                    )
                    destination_summaries.append(
                        {
                            "destination_id": destination_id,
                            "complete": False,
                            "best_mode": None,
                            "outbound_mode": None,
                            "return_mode": None,
                            "outbound_minutes": None,
                            "return_minutes": None,
                            "daily_minutes": None,
                            "weekly_minutes": None,
                            "days_per_week": days,
                        }
                    )
                    continue
                for candidate in candidates:
                    candidate["_cap_compliant"] = bool(
                        maximum is None
                        or max(candidate["_outbound"], candidate["_return"]) <= maximum
                    )
                candidates.sort(
                    key=lambda item: (
                        not item["_cap_compliant"],
                        item["_daily"],
                        mode_order.get(item["outbound_mode"], 999),
                        mode_order.get(item["return_mode"], 999),
                    )
                )
                selected = candidates[0]
                weekly = selected["_daily"] * days
                total_weekly += weekly
                total_days += days
                worst_leg = max(worst_leg, selected["_outbound"], selected["_return"])
                selected_mode = (
                    selected["outbound_mode"]
                    if selected["outbound_mode"] == selected["return_mode"]
                    else f"{selected['outbound_mode']}/{selected['return_mode']}"
                )
                destination_summaries.append(
                    {
                        "destination_id": destination_id,
                        "complete": True,
                        "best_mode": selected_mode,
                        "outbound_mode": selected["outbound_mode"],
                        "return_mode": selected["return_mode"],
                        "outbound_minutes": _round_minutes(selected["_outbound"]),
                        "return_minutes": _round_minutes(selected["_return"]),
                        "daily_minutes": _round_minutes(selected["_daily"]),
                        "weekly_minutes": _round_minutes(weekly),
                        "days_per_week": days,
                    }
                )
            selected_modes = {
                destination["best_mode"]
                for destination in destination_summaries
                if destination["complete"] and destination["best_mode"] is not None
            }
            best_mode = next(iter(selected_modes)) if len(selected_modes) == 1 else "mixed" if selected_modes else None
            over_cap = bool(complete and maximum is not None and worst_leg > maximum)
            person_summaries.append(
                {
                    "person_id": person_id,
                    "complete": complete,
                    "best_mode": best_mode,
                    "daily_minutes": _round_minutes(total_weekly / total_days)
                    if complete and total_days > 0
                    else 0.0
                    if complete
                    else None,
                    "weekly_minutes": _round_minutes(total_weekly) if complete else None,
                    "worst_leg_minutes": _round_minutes(worst_leg) if complete else None,
                    "max_minutes": maximum,
                    "over_cap": over_cap,
                    "destinations": destination_summaries,
                }
            )

        complete = bool(person_summaries) and all(person["complete"] for person in person_summaries)
        weekly_values = [
            float(person["weekly_minutes"])
            for person in person_summaries
            if person["weekly_minutes"] is not None
        ]
        over_cap_people = [person["person_id"] for person in person_summaries if person["over_cap"]]
        rankings.append(
            {
                "listing_id": listing_id,
                "complete": complete,
                "missing_routes": missing_routes,
                "people": person_summaries,
                "mean_weekly_minutes": _round_minutes(sum(weekly_values) / len(weekly_values))
                if complete and weekly_values
                else None,
                "worst_person_weekly_minutes": _round_minutes(max(weekly_values))
                if complete and weekly_values
                else None,
                "over_cap_people": over_cap_people,
                "over_cap_count": len(over_cap_people),
            }
        )

    rankings.sort(
        key=lambda row: (
            not row["complete"],
            row["over_cap_count"],
            row["mean_weekly_minutes"] if row["mean_weekly_minutes"] is not None else math.inf,
            row["worst_person_weekly_minutes"]
            if row["worst_person_weekly_minutes"] is not None
            else math.inf,
            row["listing_id"],
        )
    )
    return rankings
