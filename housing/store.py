"""Small append-only observation store. An incomplete run never deletes inventory."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

FIELDS = ("id", "source", "source_id", "url", "title", "address", "unit", "grain",
          "rent", "total_monthly_cost", "bedrooms", "bathrooms", "lat", "lon", "observed_at", "historical", "synthetic", "notes",
          "parser_version", "source_content_sha256")
FIELDS += ("sqft", "available_date", "property_type", "amenities", "pets", "parking",
           "monthly_fees", "one_time_fees", "lease_months")


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def validate_listing(row):
    if not isinstance(row, dict):
        raise ValueError("Each listing must be an object")
    result = {k: row.get(k) for k in FIELDS}
    raw_source = row.get("source")
    if raw_source is None or raw_source == "":
        raw_source = "import"
    raw_source_id = row.get("source_id")
    if raw_source_id is None or raw_source_id == "":
        raw_source_id = row.get("id")
    if raw_source_id is None:
        raw_source_id = ""
    if not isinstance(raw_source, str) or not isinstance(raw_source_id, str):
        raise ValueError("source and source_id must be strings")
    source = raw_source.strip() or "import"
    source_id = raw_source_id.strip()
    if not source_id:
        raise ValueError("Every listing needs an id or source_id stable across imports")
    if len(source) > 1000 or len(source_id) > 1000:
        raise ValueError("source and source_id must be 1000 characters or fewer")
    result["source"] = source
    result["source_id"] = source_id
    # Source-scoped identity prevents two managers' '123' records being merged.
    result["id"] = f"{source}:{source_id}"
    for field in ("title", "address", "unit", "notes", "url", "parser_version", "source_content_sha256", "available_date", "property_type"):
        if result[field] is not None:
            result[field] = str(result[field])[:10000] or None
    result["grain"] = row.get("grain") or "unknown"
    if result["grain"] not in ("unit", "floorplan", "property", "unknown"):
        raise ValueError("grain must be unit, floorplan, property or unknown")
    for field in ("rent", "total_monthly_cost", "bedrooms", "bathrooms", "lat", "lon", "sqft", "monthly_fees", "one_time_fees", "lease_months"):
        value = row.get(field)
        if value is None or value == "":
            result[field] = None
            continue
        if isinstance(value, bool):
            raise ValueError(f"{field} must be numeric or null")
        try:
            number = float(value)
        except (ValueError, TypeError):
            raise ValueError(f"{field} must be numeric or null") from None
        if not math.isfinite(number) or (field not in ("lat", "lon") and number < 0):
            raise ValueError(f"Invalid {field}")
        if field == "lat" and not -90 <= number <= 90 or field == "lon" and not -180 <= number <= 180:
            raise ValueError(f"Invalid {field}")
        result[field] = number
    if (result["lat"] is None) != (result["lon"] is None):
        raise ValueError("Provide both lat and lon or neither")
    for field in ("pets", "parking"):
        value = row.get(field)
        if value in (None, ""):
            result[field] = None
        elif isinstance(value, bool):
            result[field] = value
        elif isinstance(value, str) and value.lower() in ("true", "false", "1", "0"):
            result[field] = value.lower() in ("true", "1")
        else:
            raise ValueError(f"{field} must be true, false or null")
    amenities = row.get("amenities") or []
    if isinstance(amenities, str):
        amenities = json.loads(amenities) if amenities.strip().startswith("[") else amenities.split(";")
    if not isinstance(amenities, list) or any(not isinstance(x, str) for x in amenities):
        raise ValueError("amenities must be an array of strings")
    result["amenities"] = sorted(set(x.strip()[:200] for x in amenities if x.strip()))[:100]
    if result["url"]:
        parsed_url = urlparse(result["url"])
        if parsed_url.scheme not in ("http", "https") or not parsed_url.netloc:
            raise ValueError("Listing URLs must be absolute http or https URLs")
    for field in ("historical", "synthetic"):
        value = row.get(field, False)
        if isinstance(value, str):
            if value.lower() not in ("true", "false", "1", "0", ""):
                raise ValueError(f"{field} must be boolean")
            value = value.lower() in ("true", "1")
        elif not isinstance(value, bool):
            raise ValueError(f"{field} must be boolean")
        result[field] = value
    timestamp = row.get("observed_at") or now()
    try:
        dt = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            raise ValueError()
        result["observed_at"] = dt.astimezone(timezone.utc).isoformat()
    except (ValueError, TypeError):
        raise ValueError("observed_at must be an ISO timestamp with timezone") from None
    return result


def read_listings(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        data = list(csv.DictReader(f)) if str(path).lower().endswith(".csv") else json.load(f)
    if isinstance(data, dict):
        data = data.get("listings")
    if not isinstance(data, list):
        raise ValueError("Expected a JSON array, {listings: [...]} or CSV with a header")
    return data


class Store:
    def __init__(self, workspace):
        self.workspace = Path(workspace).expanduser().resolve()
        self.workspace.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.workspace / "housing.sqlite"
        with self.connect() as db:
            db.executescript("""
              CREATE TABLE IF NOT EXISTS observations (
                seq INTEGER PRIMARY KEY, listing_id TEXT NOT NULL, observed_at TEXT NOT NULL,
                digest TEXT NOT NULL UNIQUE, data TEXT NOT NULL);
              CREATE INDEX IF NOT EXISTS observation_identity ON observations(listing_id, observed_at);
              CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY, source TEXT NOT NULL, captured_at TEXT NOT NULL,
                status TEXT NOT NULL, count INTEGER NOT NULL, message TEXT, requests INTEGER);
              CREATE TABLE IF NOT EXISTS annotations (
                listing_id TEXT PRIMARY KEY, status TEXT NOT NULL, note TEXT NOT NULL);
              PRAGMA user_version=2;
            """)
            if "details" not in {row[1] for row in db.execute("PRAGMA table_info(runs)")}:
                db.execute("ALTER TABLE runs ADD COLUMN details TEXT")
        if os.name == "posix":
            self.path.chmod(0o600)

    def connect(self):
        return sqlite3.connect(self.path, timeout=30)

    def import_rows(self, rows):
        normalized = [validate_listing(row) for row in rows]
        inserted = 0
        with self.connect() as db:
            for row in normalized:
                cursor = db.execute("INSERT OR IGNORE INTO observations(listing_id,observed_at,digest,data) VALUES(?,?,?,?)",
                                    (row["id"], row["observed_at"], digest(row), json.dumps(row, allow_nan=False)))
                inserted += cursor.rowcount
        return {"received": len(normalized), "observations_added": inserted, "listings": len(self.listings())}

    def listings(self):
        with self.connect() as db:
            rows = db.execute("""SELECT data FROM (SELECT data, listing_id,
                ROW_NUMBER() OVER (PARTITION BY listing_id ORDER BY observed_at DESC,seq DESC) rn
                FROM observations) WHERE rn=1 ORDER BY listing_id""").fetchall()
        return [json.loads(row[0]) for row in rows]

    def annotate(self, listing_id, status="none", note=""):
        if status not in ("none", "shortlist", "rejected") or not isinstance(note, str) or len(note) > 10000:
            raise ValueError("Use shortlist, rejected or none, and a note of at most 10000 characters")
        with self.connect() as db:
            if not db.execute("SELECT 1 FROM observations WHERE listing_id=? LIMIT 1", (listing_id,)).fetchone():
                raise ValueError("Unknown listing")
            db.execute("INSERT INTO annotations VALUES(?,?,?) ON CONFLICT(listing_id) DO UPDATE SET status=excluded.status,note=excluded.note",
                       (listing_id, status, note))
        return {"id": listing_id, "status": status, "note": note}

    def review_listings(self):
        with self.connect() as db:
            annotations = {r[0]: {"status": r[1], "note": r[2]} for r in db.execute("SELECT * FROM annotations")}
            history = db.execute("""SELECT listing_id,data FROM (SELECT listing_id,data,
                ROW_NUMBER() OVER(PARTITION BY listing_id ORDER BY observed_at DESC,seq DESC) rn
                FROM observations) WHERE rn<=2 ORDER BY listing_id,rn""").fetchall()
        versions = {}
        for listing_id, raw in history:
            versions.setdefault(listing_id, []).append(json.loads(raw))
        result = []
        ignored = {"observed_at", "source_content_sha256", "parser_version"}
        for listing_id, rows in versions.items():
            row = rows[0]
            previous = rows[1] if len(rows) > 1 else None
            fields = [key for key in FIELDS if key not in ignored and previous is not None and row.get(key) != previous.get(key)]
            row["annotation"] = annotations.get(listing_id, {"status": "none", "note": ""})
            row["change"] = {"kind": "new" if previous is None else "changed" if fields else "unchanged",
                             "fields": fields, "previous_rent": previous.get("rent") if previous else None}
            result.append(row)
        return result

    def record_run(self, source, result):
        with self.connect() as db:
            details = {k: v for k, v in result.items() if k not in ("listings", "status", "message", "requests")}
            db.execute("INSERT INTO runs(source,captured_at,status,count,message,requests,details) VALUES(?,?,?,?,?,?,?)",
                       (source, now(), result["status"], len(result.get("listings", [])),
                        result.get("message", ""), result.get("requests", 0), json.dumps(details, allow_nan=False)))

    def status(self):
        with self.connect() as db:
            total = db.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
            recent = db.execute("SELECT source,captured_at,status,count,message,requests,details FROM runs ORDER BY id DESC LIMIT 20").fetchall()
        rows = self.listings()
        exceptions = []
        for row in rows:
            missing = [k for k in ("rent", "bedrooms", "bathrooms", "lat", "lon") if row[k] is None]
            if missing or row["grain"] in ("unknown", "property"):
                exceptions.append({"listing_id": row["id"], "missing": missing, "grain": row["grain"]})
        runs = [dict(zip(("source", "captured_at", "status", "count", "message", "requests"), r[:6])) | json.loads(r[6] or "{}") for r in recent]
        return {"listings": len(rows), "observations": total,
                "synthetic": sum(r["synthetic"] for r in rows),
                "historical": sum(r["historical"] for r in rows),
                "review_count": len(exceptions), "review": exceptions[:20],
                "recent_runs": runs, "runs": runs}


def export_csv(rows):
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=FIELDS, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        # Avoid formulas when users open untrusted provider text in a spreadsheet.
        safe = {k: (json.dumps(v) if isinstance(v, (list, dict)) else "'" + v if isinstance(v, str) and v.lstrip().startswith(("=", "+", "-", "@")) else v) for k, v in row.items()}
        writer.writerow(safe)
    return output.getvalue()


def duplicate_groups(rows):
    """Suggest exact address/unit matches; never collapse different or unnamed units."""
    groups = {}
    for row in rows:
        if row.get("grain") != "unit" or not row.get("address") or not row.get("unit"):
            continue
        key = tuple(re.sub(r"[^a-z0-9]", "", str(row[k]).lower()) for k in ("address", "unit"))
        groups.setdefault(key, []).append(row["id"])
    return [ids for ids in groups.values() if len(ids) > 1]
