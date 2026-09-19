"""Private browser-assisted coverage ledger and normalized capture import.

This module does not launch a browser or an agent.  It accepts evidence captured
elsewhere, validates the complete envelope, appends observations through Store,
and keeps a small source-scoped resume ledger in the private workspace.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from typing import Mapping
from urllib.parse import urlsplit

from .config import load_config
from .sources import source_catalog
from .store import now, validate_listing


LEDGER_NAME = "assisted-ledger.json"
LEDGER_VERSION = 1
CAPTURE_STATUSES = frozenset({"partial", "complete", "blocked", "error"})
_SOURCE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_MAX_PAGES = 1_000
_MAX_LISTINGS = 5_000


def _ledger_path(store) -> Path:
    return Path(store.workspace) / LEDGER_NAME


def _read_ledger(store) -> dict:
    path = _ledger_path(store)
    if not path.exists():
        return {"schema_version": LEDGER_VERSION, "sources": {}}
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read assisted coverage ledger: {exc}") from None
    if (not isinstance(document, dict)
            or document.get("schema_version") != LEDGER_VERSION
            or not isinstance(document.get("sources"), dict)):
        raise ValueError("Invalid assisted coverage ledger")
    return document


def _write_ledger(store, ledger: Mapping[str, object]) -> None:
    path = _ledger_path(store)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(ledger, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    if os.name == "posix":
        temp.chmod(0o600)
    temp.replace(path)


def _timestamp(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be an ISO timestamp with timezone")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError
    except ValueError:
        raise ValueError(f"{field} must be an ISO timestamp with timezone") from None
    return parsed.astimezone(timezone.utc).isoformat()


def _absolute_url(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be an absolute HTTP(S) URL")
    value = value.strip()
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise ValueError(f"{field} must be an absolute HTTP(S) URL") from None
    if (parsed.scheme.lower() not in ("http", "https") or not parsed.hostname
            or parsed.username is not None or parsed.password is not None):
        raise ValueError(f"{field} must be an absolute HTTP(S) URL without credentials")
    if port is not None and not 1 <= port <= 65535:
        raise ValueError(f"{field} has an invalid port")
    return value


def _origin(url: str) -> tuple[str, str, int]:
    parsed = urlsplit(url)
    default_port = 443 if parsed.scheme.lower() == "https" else 80
    return parsed.scheme.lower(), (parsed.hostname or "").lower(), parsed.port or default_port


def _same_origin(url: str, expected: tuple[str, str, int], field: str) -> None:
    if _origin(url) != expected:
        raise ValueError(f"{field} must use the declared source origin")


def _source_sets(config: Mapping[str, object]) -> tuple[dict[str, dict], dict[str, dict]]:
    configured = {source["id"]: deepcopy(source) for source in config.get("sources", [])}
    catalog = {source["id"]: source for source in source_catalog(config.get("city") or "Chicago")}
    return configured, catalog


def _validate_source(capture_source: object, config: Mapping[str, object]) -> tuple[str, dict, str | None]:
    if not isinstance(capture_source, Mapping):
        raise ValueError("source must be an object with an id")
    source_id = capture_source.get("id")
    if not isinstance(source_id, str) or not _SOURCE_ID.fullmatch(source_id):
        raise ValueError("source.id must be a stable identifier using letters, numbers, dot, underscore or hyphen")

    configured, catalog = _source_sets(config)
    matched = configured.get(source_id) or catalog.get(source_id)
    if matched is None:
        raise ValueError(
            f"Unknown source {source_id!r}; add a declared custom source to workspace configuration first"
        )
    declared_adapter = capture_source.get("adapter")
    if declared_adapter is not None and declared_adapter != matched.get("adapter"):
        raise ValueError("source.adapter does not match the configured or catalog source")

    matched_url = matched.get("url")
    capture_url = capture_source.get("url")
    authoritative_url = None
    if matched_url:
        authoritative_url = _absolute_url(matched_url, "configured source URL")
        if capture_url is not None:
            capture_url = _absolute_url(capture_url, "source.url")
            _same_origin(capture_url, _origin(authoritative_url), "source.url")
    elif capture_url is not None:
        authoritative_url = _absolute_url(capture_url, "source.url")
    else:
        raise ValueError("A source without a configured URL must declare source.url in the capture")
    return source_id, matched, authoritative_url


def _criteria(value: object) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("criteria must be an object")
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError):
        raise ValueError("criteria must contain JSON values without NaN or infinity") from None
    if len(encoded) > 100_000:
        raise ValueError("criteria is too large")
    return deepcopy(value)


def _normalize_rows(rows: object, source_id: str, observed_at: str,
                    expected_origin: tuple[str, str, int]) -> list[dict]:
    if not isinstance(rows, list) or len(rows) > _MAX_LISTINGS:
        raise ValueError(f"listings must be an array of at most {_MAX_LISTINGS} records")
    normalized: list[dict] = []
    seen: set[str] = set()
    for index, original in enumerate(rows):
        if not isinstance(original, dict):
            raise ValueError(f"listings[{index}] must be an object")
        row = dict(original)
        if row.get("source") not in (None, "", source_id):
            raise ValueError(f"listings[{index}].source does not match source.id")
        provider_id = row.get("source_id")
        supplied_id = row.get("id")
        if provider_id in (None, ""):
            if not isinstance(supplied_id, str) or not supplied_id.strip():
                raise ValueError(f"listings[{index}] needs a stable source_id or id")
            prefix = f"{source_id}:"
            provider_id = supplied_id[len(prefix):] if supplied_id.startswith(prefix) else supplied_id
        elif supplied_id not in (None, "", provider_id, f"{source_id}:{provider_id}"):
            raise ValueError(f"listings[{index}].id and source_id disagree")
        if not isinstance(provider_id, str) or not provider_id.strip():
            raise ValueError(f"listings[{index}].source_id must be non-empty text")
        row["source"] = source_id
        row["source_id"] = provider_id.strip()
        if row.get("observed_at") not in (None, ""):
            item_timestamp = _timestamp(row["observed_at"], f"listings[{index}].observed_at")
            if item_timestamp != observed_at:
                raise ValueError(f"listings[{index}].observed_at must equal the capture observed_at")
        row["observed_at"] = observed_at
        row.setdefault("parser_version", "browser-assisted-v1")
        item = validate_listing(row)
        if item["source_id"] in seen:
            raise ValueError(f"Duplicate source_id in capture: {item['source_id']}")
        seen.add(item["source_id"])
        if item.get("url"):
            item_url = _absolute_url(item["url"], f"listings[{index}].url")
            _same_origin(item_url, expected_origin, f"listings[{index}].url")
        normalized.append(item)
    return normalized


def _validate_capture(store, capture: object) -> dict:
    if not isinstance(capture, Mapping):
        raise ValueError("Assisted capture must be a JSON object")
    config = load_config(store.workspace)
    source_id, matched_source, authoritative_url = _validate_source(capture.get("source"), config)
    expected_origin = _origin(authoritative_url)

    search_url = _absolute_url(capture.get("search_url"), "search_url")
    _same_origin(search_url, expected_origin, "search_url")
    observed_at = _timestamp(capture.get("observed_at"), "observed_at")
    status = capture.get("status")
    if status not in CAPTURE_STATUSES:
        raise ValueError("status must be partial, complete, blocked or error")

    raw_pages = capture.get("pages_visited", [])
    if not isinstance(raw_pages, list) or len(raw_pages) > _MAX_PAGES:
        raise ValueError(f"pages_visited must be an array of at most {_MAX_PAGES} URLs")
    pages: list[str] = []
    seen_pages: set[str] = set()
    for index, raw_url in enumerate(raw_pages):
        page_url = _absolute_url(raw_url, f"pages_visited[{index}]")
        _same_origin(page_url, expected_origin, f"pages_visited[{index}]")
        if page_url in seen_pages:
            raise ValueError("pages_visited must not contain duplicate URLs")
        seen_pages.add(page_url)
        pages.append(page_url)

    next_url = capture.get("next_url")
    if next_url in (None, ""):
        next_url = None
    else:
        next_url = _absolute_url(next_url, "next_url")
        _same_origin(next_url, expected_origin, "next_url")
    if status == "complete" and next_url:
        raise ValueError("A complete searched-pages scope cannot include next_url")
    if status == "complete" and not pages:
        raise ValueError("complete requires at least one explicitly visited page")

    note = capture.get("evidence_note", "")
    if not isinstance(note, str) or len(note) > 10_000:
        raise ValueError("evidence_note must be text of at most 10000 characters")
    rows = _normalize_rows(capture.get("listings", []), source_id, observed_at, expected_origin)
    if status in ("blocked", "error") and rows:
        raise ValueError("blocked and error captures must be status-only; use partial when records were captured")

    return {
        "source_id": source_id,
        "source": {
            "id": source_id,
            "name": matched_source.get("name") or capture["source"].get("name") or source_id,
            "adapter": matched_source.get("adapter"),
            "url": authoritative_url,
        },
        "search_url": search_url,
        "observed_at": observed_at,
        "status": status,
        "pages_visited": pages,
        "next_url": next_url,
        "evidence_note": note.strip(),
        "criteria": _criteria(capture.get("criteria")),
        "listings": rows,
    }


def _ledger_entry(previous: Mapping[str, object] | None, capture: Mapping[str, object],
                  imported: Mapping[str, object]) -> dict:
    previous = previous or {}
    same_criteria = previous.get("criteria", {}) == capture["criteria"]
    # A resumed browser capture commonly starts at the saved next URL. Preserve
    # the original search scope while recording that exact resumed page.
    same_scope = (same_criteria and (
        previous.get("search_url") == capture["search_url"]
        or previous.get("resume_url") == capture["search_url"]
    ))
    if previous.get("observed_at"):
        prior_time = datetime.fromisoformat(str(previous["observed_at"]).replace("Z", "+00:00"))
        capture_time = datetime.fromisoformat(str(capture["observed_at"]).replace("Z", "+00:00"))
        if capture_time < prior_time:
            raise ValueError("Capture observed_at predates the source's current assisted progress")

    pages = list(previous.get("pages_visited", [])) if same_scope else []
    for page in capture["pages_visited"]:
        if page not in pages:
            pages.append(page)
    if capture["status"] == "complete":
        resume_url = None
    else:
        resume_url = capture["next_url"] or (previous.get("resume_url") if same_scope else None)
    records_captured = len(capture["listings"])
    observations_added = int(imported["observations_added"])
    if same_scope:
        records_captured += int(previous.get("records_captured", 0))
        observations_added += int(previous.get("observations_added", 0))
    return {
        "source": capture["source"],
        "status": capture["status"],
        "scope": "searched_pages_only",
        "city_complete": False,
        "method": "browser",
        "observed_at": capture["observed_at"],
        "search_url": previous.get("search_url") if same_scope else capture["search_url"],
        "criteria": capture["criteria"],
        "pages_visited": pages,
        "last_pages_visited": capture["pages_visited"],
        "resume_url": resume_url,
        "records_captured": records_captured,
        "observations_added": observations_added,
        "captures": int(previous.get("captures", 0)) + 1,
        "evidence_note": capture["evidence_note"],
    }


def ingest(store, capture: Mapping[str, object] | str | Path) -> dict:
    """Validate and import one browser capture, then update source progress.

    Validation of the envelope and every listing finishes before Store or the
    private ledger is written.  ``complete`` means only that this declared
    searched-pages traversal reported no next page.
    """

    if isinstance(capture, (str, Path)):
        try:
            capture = json.loads(Path(capture).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Cannot read assisted capture: {exc}") from None
    validated = _validate_capture(store, capture)
    ledger = _read_ledger(store)
    previous = ledger["sources"].get(validated["source_id"])

    # Build the prospective ledger entry before writes, including stale-time
    # validation. Store.import_rows independently validates the entire list in
    # one transaction before appending any observation.
    projected_import = {"observations_added": 0}
    _ledger_entry(previous, validated, projected_import)
    if validated["listings"]:
        imported = store.import_rows(validated["listings"])
    else:
        imported = {
            "received": 0,
            "observations_added": 0,
            "listings": len(store.listings()),
        }

    entry = _ledger_entry(previous, validated, imported)
    run = {
        "status": validated["status"],
        "message": validated["evidence_note"],
        "requests": 0,
        "listings": validated["listings"],
        "method": "browser",
        "observed_at": validated["observed_at"],
        "search_url": validated["search_url"],
        "pages_visited": validated["pages_visited"],
        "next_url": validated["next_url"],
        "criteria": validated["criteria"],
        "scope": "searched_pages_only",
        "city_complete": False,
        "partial": validated["status"] == "partial",
        "coverage": {
            "pages": len(validated["pages_visited"]),
            "records": len(validated["listings"]),
        },
    }
    store.record_run(validated["source_id"], run)
    ledger["sources"][validated["source_id"]] = entry
    ledger["updated_at"] = now()
    _write_ledger(store, ledger)

    return {
        "source": validated["source_id"],
        "status": validated["status"],
        "method": "browser",
        "scope": "searched_pages_only",
        "city_complete": False,
        "imported": imported,
        "progress": {
            "pages_visited": len(entry["pages_visited"]),
            "resume_url": entry["resume_url"],
            "records_captured": entry["records_captured"],
            "observed_at": entry["observed_at"],
        },
    }


def _latest_http_runs(store) -> dict[str, dict]:
    result: dict[str, dict] = {}
    with store.connect() as db:
        rows = db.execute(
            "SELECT source,captured_at,status,count,message,requests,details FROM runs ORDER BY id DESC"
        ).fetchall()
    fields = ("source", "captured_at", "status", "count", "message", "requests")
    for row in rows:
        source_id = row[0]
        if source_id in result:
            continue
        try:
            details = json.loads(row[6] or "{}")
        except json.JSONDecodeError:
            details = {}
        run = dict(zip(fields, row[:6])) | details
        if run.get("method") != "browser":
            result[source_id] = run
    return result


def _plan_action(source: Mapping[str, object], progress: Mapping[str, object] | None,
                 http: Mapping[str, object] | None) -> tuple[int, str, str, str | None]:
    adapter = source.get("adapter")
    url = source.get("url")
    if progress:
        resume_url = progress.get("resume_url")
        status = progress.get("status")
        if resume_url and status in ("partial", "blocked", "error"):
            return 0, "resume_browser", "resume_point_available", str(resume_url)
        if status == "partial":
            return 5, "review_browser", "partial_capture_has_no_resume_url", None
        if status in ("blocked", "error"):
            return 20, "review_browser", f"browser_{status}", None
        if status == "complete":
            return 90, "review_later", "searched_pages_scope_complete", None

    if http:
        http_status = http.get("status")
        resume_url = http.get("resume_url")
        partial = http_status == "partial" or http.get("partial") is True
        if resume_url and partial:
            return 15, "resume_http", "http_resume_point_available", str(resume_url)
        if partial:
            return 35, "review_source", "latest_http_partial_without_resume", str(url) if url else None
        if adapter == "assisted" and http_status in ("unimplemented", "blocked", "error"):
            return 8, "browse", f"http_{http_status}", str(url) if url else None
        if http_status in ("unimplemented", "blocked", "error"):
            return 30, "review_source", f"http_{http_status}", str(url) if url else None
        if http_status in ("success", "empty", "complete"):
            reasons = {
                "success": "latest_http_success",
                "empty": "latest_http_explicit_empty",
                "complete": "latest_http_scope_complete",
            }
            return 100, "none", reasons[http_status], None
    if adapter == "assisted":
        if url:
            return 10, "browse", "untouched_assisted_source", str(url)
        return 25, "review_source", "assisted_source_needs_declared_url", None
    if source.get("enabled") is True:
        return 40, "collect_http", "enabled_source_not_yet_observed", str(url) if url else None
    return 60, "review_source", "disabled_source_not_yet_observed", str(url) if url else None


def plan(store) -> dict:
    """Return a deterministic, non-executing coverage and resume plan."""

    config = load_config(store.workspace)
    configured, catalog = _source_sets(config)
    ledger = _read_ledger(store)
    http_runs = _latest_http_runs(store)

    merged: dict[str, dict] = {}
    order: dict[str, int] = {}
    for index, (source_id, source) in enumerate(catalog.items()):
        merged[source_id] = deepcopy(source)
        order[source_id] = index
    for source_id, source in configured.items():
        merged[source_id] = {**merged.get(source_id, {}), **deepcopy(source), "configured": True}
        order.setdefault(source_id, len(order))
    for source_id, progress in ledger["sources"].items():
        if source_id not in merged:
            merged[source_id] = {**progress.get("source", {}), "id": source_id, "orphaned": True}
            order[source_id] = len(order)

    items = []
    for source_id, source in merged.items():
        progress = ledger["sources"].get(source_id)
        http = http_runs.get(source_id)
        priority, action, reason, resume_url = _plan_action(source, progress, http)
        if source.get("orphaned"):
            priority, action, reason = 2, "review_configuration", "source_no_longer_configured"
        item = {
            "source": {
                "id": source_id,
                "name": source.get("name") or source_id,
                "adapter": source.get("adapter"),
                "browser_recipe": source.get("browser_recipe"),
                "url": source.get("url"),
                "enabled": source.get("enabled") is True,
                "configured": source_id in configured,
                "catalog_source": source_id in catalog,
            },
            "priority": priority,
            "action": action,
            "reason": reason,
            "resume_url": resume_url,
            "progress": None if not progress else {
                "status": progress.get("status"),
                "scope": "searched_pages_only",
                "city_complete": False,
                "observed_at": progress.get("observed_at"),
                "pages_visited": len(progress.get("pages_visited", [])),
                "records_captured": progress.get("records_captured", 0),
                "resume_url": progress.get("resume_url"),
                "criteria": progress.get("criteria", {}),
                "evidence_note": progress.get("evidence_note", ""),
            },
            "http_run": None if not http else {
                "status": http.get("status"),
                "captured_at": http.get("captured_at"),
                "message": http.get("message", ""),
                "resume_url": http.get("resume_url"),
            },
        }
        items.append(item)
    items.sort(key=lambda item: (item["priority"], order[item["source"]["id"]]))

    return {
        "city": config.get("city"),
        "city_complete": False,
        "scope": "declared_sources_and_searched_pages",
        "generated_at": now(),
        "summary": {
            "sources": len(items),
            "assisted_sources": sum(item["source"]["adapter"] == "assisted" for item in items),
            "untouched_assisted": sum(item["reason"] == "untouched_assisted_source" for item in items),
            "resume_points": sum(bool(item["resume_url"]) and item["action"].startswith("resume") for item in items),
        },
        "sources": items,
        "execution": {
            "network_requests": 0,
            "browser_opened": False,
            "agent_runtime_started": False,
        },
    }


__all__ = ["ingest", "plan"]
