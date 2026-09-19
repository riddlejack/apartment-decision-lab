from __future__ import annotations

import csv
import json
import zipfile
from pathlib import Path

import pytest

from housing import routing


def _write_gtfs(path: Path, start: str = "20260701", end: str = "20260731") -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "calendar.txt",
            "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
            f"weekday,1,1,1,1,1,0,0,{start},{end}\n",
        )


def _config(network_dir: Path) -> dict:
    return {
        "timezone": "America/Chicago",
        "routing": {
            "engine": "r5r",
            "network_dir": str(network_dir),
            "date": "2026-07-21",
            "outbound_time": "08:15",
            "return_time": "17:45",
            "time_window_minutes": 5,
            "threads": 1,
            "max_memory_gb": 2,
            "cache": False,
        },
        "people": [
            {
                "id": "p1",
                "name": "One",
                "modes": ["walk", "transit"],
                "max_minutes": 35,
                "destinations": [
                    {
                        "id": "library",
                        "name": "Library",
                        "lat": 41.88,
                        "lon": -87.63,
                        "days_per_week": 3,
                    }
                ],
            },
            {
                "id": "p2",
                "name": "Two",
                "modes": ["bike"],
                "max_minutes": 20,
                "destinations": [
                    {
                        "id": "park",
                        "name": "Park",
                        "lat": 41.91,
                        "lon": -87.64,
                        "days_per_week": 2,
                        "outbound_time": "09:00",
                        "return_time": "18:30",
                    }
                ],
            },
        ],
    }


def _fake_engine(*, origins, destinations, jobs, **kwargs):
    rows = []
    for job in jobs:
        destination_ids = job["destination_keys"].split(";")
        if job["direction"] == "outbound":
            pairs = ((origin["id"], destination_id) for origin in origins for destination_id in destination_ids)
        else:
            pairs = ((destination_id, origin["id"]) for destination_id in destination_ids for origin in origins)
        base = {"walk": 28, "transit": 19, "bike": 14, "drive": 8}[job["mode"]]
        direction_add = 0 if job["direction"] == "outbound" else 4
        for from_id, to_id in pairs:
            rows.append(
                {
                    "job_id": job["job_id"],
                    "direction": job["direction"],
                    "mode": job["mode"],
                    "from_id": from_id,
                    "to_id": to_id,
                    "minutes": str(base + direction_add),
                }
            )
    return rows, {"r5r_version": "test-engine"}


def test_added_origin_only_computes_new_coordinates(tmp_path, monkeypatch):
    network = tmp_path / "network"
    network.mkdir()
    _write_gtfs(network / "feed.zip")
    config = _config(network)
    config["routing"]["cache"] = True
    calls = []
    def engine(**kwargs):
        calls.append(len(kwargs["origins"]))
        return _fake_engine(**kwargs)
    monkeypatch.setattr(routing, "_execute_r5r", engine)
    listings = [{"id": "a", "lat": 41.89, "lon": -87.62}, {"id": "b", "lat": 41.89, "lon": -87.62}]
    first = routing.compute_routes(listings, config, tmp_path / "routes")
    listings.append({"id": "c", "lat": 41.90, "lon": -87.65})
    second = routing.compute_routes(listings, config, tmp_path / "routes")
    assert calls == [1, 1]
    assert {r["listing_id"] for r in second["results"]} == {"a", "b", "c"}
    assert second["engine"]["metadata"]["origins_reused"] == 1
    assert len(first["results"]) == 6


def test_compute_respects_person_modes_direction_times_and_weights(tmp_path, monkeypatch):
    network = tmp_path / "network"
    network.mkdir()
    _write_gtfs(network / "public-transit.zip")
    config = _config(network)
    monkeypatch.setattr(routing, "_execute_r5r", _fake_engine)

    payload = routing.compute_routes(
        [{"id": "home", "lat": 41.89, "lon": -87.62}], config, tmp_path / "routes"
    )

    assert payload["status"] == "success"
    keyed = {
        (row["person_id"], row["destination_id"], row["mode"]): row
        for row in payload["results"]
    }
    assert set(keyed) == {
        ("p1", "library", "walk"),
        ("p1", "library", "transit"),
        ("p2", "park", "bike"),
    }
    transit = keyed[("p1", "library", "transit")]
    assert transit["outbound_time"] == "08:15"
    assert transit["return_time"] == "17:45"
    assert transit["outbound_minutes"] == 19
    assert transit["return_minutes"] == 23
    assert transit["weekly_minutes"] == 126
    bike = keyed[("p2", "park", "bike")]
    assert (bike["outbound_time"], bike["return_time"]) == ("09:00", "18:30")
    assert bike["capped"] is False


def test_drive_requires_opt_in_then_adds_parking_per_leg(tmp_path, monkeypatch):
    network = tmp_path / "network"
    network.mkdir()
    config = _config(network)
    config["people"] = [
        {
            "id": "driver",
            "modes": ["drive"],
            "max_minutes": 10,
            "destinations": [
                {"id": "civic", "lat": 41.9, "lon": -87.65, "days_per_week": 1}
            ],
        }
    ]
    monkeypatch.setattr(routing, "_execute_r5r", _fake_engine)

    denied = routing.compute_routes(
        [{"id": "home", "lat": 41.89, "lon": -87.62}], config, tmp_path / "denied"
    )["results"][0]
    assert denied["roundtrip_valid"] is False
    assert denied["unavailable_reason"] == "drive_requires_explicit_opt_in"
    assert denied["outbound_minutes"] is None

    config["routing"]["drive_enabled"] = True
    config["routing"]["drive_parking_minutes"] = 3
    allowed = routing.compute_routes(
        [{"id": "home", "lat": 41.89, "lon": -87.62}], config, tmp_path / "allowed"
    )["results"][0]
    assert allowed["model"] == "free_flow_osm_plus_parking"
    assert (allowed["outbound_minutes"], allowed["return_minutes"]) == (11, 15)
    assert allowed["daily_minutes"] == 26
    assert allowed["capped"] is True


def test_rank_keeps_missing_null_and_never_builds_mixed_personal_vehicle_roundtrip():
    listings = [{"id": "a"}, {"id": "b"}]
    people = [
        {
            "id": "p",
            "modes": ["bike", "drive"],
            "max_minutes": 25,
            "destinations": [{"id": "work", "days_per_week": 4}],
        }
    ]
    payload = {
        "results": [
            {
                "listing_id": "a",
                "person_id": "p",
                "destination_id": "work",
                "mode": "bike",
                "outbound_minutes": 10,
                "return_minutes": None,
                "roundtrip_valid": False,
            },
            {
                "listing_id": "a",
                "person_id": "p",
                "destination_id": "work",
                "mode": "drive",
                "outbound_minutes": None,
                "return_minutes": 12,
                "roundtrip_valid": False,
            },
            {
                "listing_id": "b",
                "person_id": "p",
                "destination_id": "work",
                "mode": "bike",
                "outbound_minutes": 20,
                "return_minutes": 30,
                "roundtrip_valid": True,
            },
        ]
    }

    ranked = routing.rank_listings(listings, people, payload)

    assert [row["listing_id"] for row in ranked] == ["b", "a"]
    complete, missing = ranked
    assert complete["people"][0]["weekly_minutes"] == 200
    assert complete["people"][0]["daily_minutes"] == 50
    assert complete["people"][0]["worst_leg_minutes"] == 30
    assert complete["people"][0]["over_cap"] is True
    assert missing["complete"] is False
    assert missing["mean_weekly_minutes"] is None
    assert missing["people"][0]["daily_minutes"] is None
    assert missing["missing_routes"][0]["reason"] == "no_valid_roundtrip_with_allowed_modes"


def test_rank_weights_destinations_and_reports_mixed_best_mode():
    people = [
        {
            "id": "p",
            "modes": ["walk", "bike"],
            "max_minutes": 30,
            "destinations": [
                {"id": "one", "days_per_week": 1},
                {"id": "two", "days_per_week": 3},
            ],
        }
    ]
    payload = {
        "results": [
            {
                "listing_id": "x",
                "person_id": "p",
                "destination_id": "one",
                "mode": "walk",
                "outbound_minutes": 10,
                "return_minutes": 10,
                "roundtrip_valid": True,
            },
            {
                "listing_id": "x",
                "person_id": "p",
                "destination_id": "one",
                "mode": "bike",
                "outbound_minutes": 12,
                "return_minutes": 12,
                "roundtrip_valid": True,
            },
            {
                "listing_id": "x",
                "person_id": "p",
                "destination_id": "two",
                "mode": "walk",
                "outbound_minutes": 30,
                "return_minutes": 30,
                "roundtrip_valid": True,
            },
            {
                "listing_id": "x",
                "person_id": "p",
                "destination_id": "two",
                "mode": "bike",
                "outbound_minutes": 15,
                "return_minutes": 17,
                "roundtrip_valid": True,
            },
        ]
    }

    person = routing.rank_listings([{"id": "x"}], people, payload)[0]["people"][0]
    assert person["best_mode"] == "mixed"
    assert person["weekly_minutes"] == 116
    assert person["daily_minutes"] == 29
    assert person["over_cap"] is False


def test_rank_can_pair_walk_outbound_with_transit_return():
    people = [
        {
            "id": "p",
            "modes": ["walk", "transit"],
            "max_minutes": 20,
            "destinations": [{"id": "work", "days_per_week": 1}],
        }
    ]
    payload = {
        "results": [
            {
                "listing_id": "x",
                "person_id": "p",
                "destination_id": "work",
                "mode": "walk",
                "outbound_minutes": 12,
                "return_minutes": None,
                "roundtrip_valid": False,
            },
            {
                "listing_id": "x",
                "person_id": "p",
                "destination_id": "work",
                "mode": "transit",
                "outbound_minutes": None,
                "return_minutes": 15,
                "roundtrip_valid": False,
            },
        ]
    }

    person = routing.rank_listings([{"id": "x"}], people, payload)[0]["people"][0]
    destination = person["destinations"][0]
    assert person["complete"] is True
    assert destination["best_mode"] == "walk/transit"
    assert (destination["outbound_mode"], destination["return_mode"]) == ("walk", "transit")
    assert destination["daily_minutes"] == 27


def test_rank_prefers_cap_compliant_pair_before_faster_breach():
    people = [
        {
            "id": "p",
            "modes": ["walk", "transit", "bike"],
            "max_minutes": 20,
            "destinations": [{"id": "work", "days_per_week": 1}],
        }
    ]
    payload = {
        "results": [
            {
                "listing_id": "x",
                "person_id": "p",
                "destination_id": "work",
                "mode": "walk",
                "outbound_minutes": 25,
                "return_minutes": 25,
                "roundtrip_valid": True,
            },
            {
                "listing_id": "x",
                "person_id": "p",
                "destination_id": "work",
                "mode": "transit",
                "outbound_minutes": 18,
                "return_minutes": 18,
                "roundtrip_valid": True,
            },
            {
                "listing_id": "x",
                "person_id": "p",
                "destination_id": "work",
                "mode": "bike",
                "outbound_minutes": 9,
                "return_minutes": 22,
                "roundtrip_valid": True,
            },
        ]
    }

    destination = routing.rank_listings([{"id": "x"}], people, payload)[0]["people"][0]["destinations"][0]
    assert destination["best_mode"] == "transit"
    assert destination["daily_minutes"] == 36


def test_zero_weight_destination_does_not_create_missing_route_or_cap_breach():
    people = [
        {
            "id": "p",
            "modes": ["walk"],
            "max_minutes": 1,
            "destinations": [{"id": "unused", "days_per_week": 0}],
        }
    ]
    ranking = routing.rank_listings([{"id": "x"}], people, {"results": []})[0]
    assert ranking["complete"] is True
    assert ranking["missing_routes"] == []
    assert ranking["people"][0]["daily_minutes"] == 0
    assert ranking["people"][0]["weekly_minutes"] == 0
    assert ranking["people"][0]["over_cap"] is False
    assert ranking["people"][0]["destinations"][0]["ignored_zero_weight"] is True


def test_zero_weight_destination_does_not_make_active_best_mode_mixed():
    people = [
        {
            "id": "p",
            "modes": ["walk"],
            "max_minutes": 30,
            "destinations": [
                {"id": "active", "days_per_week": 1},
                {"id": "unused", "days_per_week": 0},
            ],
        }
    ]
    payload = {
        "results": [
            {
                "listing_id": "x",
                "person_id": "p",
                "destination_id": "active",
                "mode": "walk",
                "outbound_minutes": 10,
                "return_minutes": 10,
                "roundtrip_valid": True,
            }
        ]
    }
    person = routing.rank_listings([{"id": "x"}], people, payload)[0]["people"][0]
    assert person["best_mode"] == "walk"


def test_fingerprints_detect_geometry_and_destination_changes(tmp_path):
    network = tmp_path / "network"
    network.mkdir()
    config = _config(network)
    listings = [{"id": "home", "lat": 41.1, "lon": -87.1}]
    request = routing.request_fingerprint(listings, config)
    payload = {
        "schema_version": routing.SCHEMA_VERSION,
        "request_fingerprint": request,
    }
    assert routing.routes_match(listings, config, payload)

    moved = [{"id": "home", "lat": 41.2, "lon": -87.1}]
    assert not routing.routes_match(moved, config, payload)
    changed = json.loads(json.dumps(config))
    changed["people"][0]["destinations"][0]["return_time"] = "19:00"
    assert routing.config_fingerprint(changed) != routing.config_fingerprint(config)
    assert not routing.routes_match(listings, changed, payload)


def test_weight_and_cap_changes_reuse_geometry_cache_and_refresh_values(tmp_path, monkeypatch):
    network = tmp_path / "network"
    network.mkdir()
    config = _config(network)
    config["people"] = config["people"][:1]
    config["people"][0]["modes"] = ["walk"]
    config["routing"]["cache"] = True
    listings = [{"id": "home", "lat": 41.89, "lon": -87.62}]
    monkeypatch.setattr(routing, "_execute_r5r", _fake_engine)
    first = routing.compute_routes(listings, config, tmp_path / "routes")
    assert first["results"][0]["weekly_minutes"] == 180
    physical_fingerprint = first["request_fingerprint"]

    config["people"][0]["max_minutes"] = 20
    config["people"][0]["destinations"][0]["days_per_week"] = 1

    def should_not_run(**kwargs):
        raise AssertionError("preference-only edit reran the routing engine")

    monkeypatch.setattr(routing, "_execute_r5r", should_not_run)
    second = routing.compute_routes(listings, config, tmp_path / "routes")
    assert second["cache"]["hit"] is True
    assert second["request_fingerprint"] == physical_fingerprint
    assert second["results"][0]["weekly_minutes"] == 60
    assert second["results"][0]["max_minutes"] == 20
    assert second["results"][0]["capped"] is True
    assert second["preference_fingerprint"] != first["preference_fingerprint"]


def test_gtfs_date_outside_coverage_is_rejected(tmp_path, monkeypatch):
    network = tmp_path / "network"
    network.mkdir()
    _write_gtfs(network / "public-transit.zip", start="20260101", end="20260131")
    config = _config(network)
    monkeypatch.setattr(routing, "_execute_r5r", _fake_engine)

    with pytest.raises(routing.RoutingError, match="outside GTFS calendar coverage"):
        routing.compute_routes(
            [{"id": "home", "lat": 41.89, "lon": -87.62}], config, tmp_path / "routes"
        )


def test_shortlist_limits_work_and_max_origins_blocks_accidental_bulk_run(tmp_path, monkeypatch):
    network = tmp_path / "network"
    network.mkdir()
    config = _config(network)
    config["people"][0]["modes"] = ["walk"]
    config["people"] = config["people"][:1]
    config["routing"]["max_origins"] = 1
    monkeypatch.setattr(routing, "_execute_r5r", _fake_engine)
    listings = [
        {"id": "shortlisted", "lat": 41.89, "lon": -87.62},
        {"id": "market-noise", "lat": 41.90, "lon": -87.61},
    ]

    with pytest.raises(routing.RoutingError, match="above max_origins=1"):
        routing.compute_routes(listings, config, tmp_path / "blocked")

    config["routing"]["listing_ids"] = ["shortlisted"]
    payload = routing.compute_routes(listings, config, tmp_path / "scoped")
    assert {row["listing_id"] for row in payload["results"]} == {"shortlisted"}
    assert payload["summary"]["origin_count"] == 1
    assert payload["summary"]["excluded_origin_count"] == 1


def test_newer_network_source_invalidates_stale_engine_cache(tmp_path, monkeypatch):
    network = tmp_path / "network"
    network.mkdir()
    cache = network / "network.dat"
    cache.write_bytes(b"old cache")
    source = network / "streets.osm.pbf"
    source.write_bytes(b"new streets")
    cache.touch()
    source.touch()
    cache_time = cache.stat().st_mtime_ns
    newer = cache_time + 1_000_000_000
    import os

    os.utime(source, ns=(newer, newer))
    config = _config(network)
    config["people"][0]["modes"] = ["walk"]
    config["people"] = config["people"][:1]
    monkeypatch.setattr(routing, "_execute_r5r", _fake_engine)

    with pytest.raises(routing.RoutingError, match="predates source"):
        routing.compute_routes(
            [{"id": "home", "lat": 41.89, "lon": -87.62}], config, tmp_path / "routes"
        )


def test_engine_orientation_correction_is_per_job_and_evidence_based():
    jobs = [
        {
            "job_id": "walk-return",
            "direction": "return",
            "mode": "walk",
            "destination_keys": "destination-a",
        },
        {
            "job_id": "transit-return",
            "direction": "return",
            "mode": "transit",
            "destination_keys": "destination-a",
        },
    ]
    # Unequal tables (3 homes, 1 destination) and unequal id namespaces match
    # the installed r5r 2.4.0 behavior observed in the live proof: only the
    # direct-WALK return job emitted the reverse of the requested orientation.
    rows = [
        {
            "job_id": "walk-return",
            "direction": "return",
            "mode": "walk",
            "from_id": "home-a",
            "to_id": "destination-a",
            "minutes": "35",
        },
        {
            "job_id": "walk-return",
            "direction": "return",
            "mode": "walk",
            "from_id": "home-b",
            "to_id": "destination-a",
            "minutes": "50",
        },
        {
            "job_id": "transit-return",
            "direction": "return",
            "mode": "transit",
            "from_id": "destination-a",
            "to_id": "home-c",
            "minutes": "28",
        },
    ]

    normalized = routing._normalize_engine_orientation(
        rows, jobs, {"home-a", "home-b", "home-c"}
    )
    walk = [row for row in normalized if row["job_id"] == "walk-return"]
    transit = [row for row in normalized if row["job_id"] == "transit-return"]
    assert {(row["from_id"], row["to_id"]) for row in walk} == {
        ("destination-a", "home-a"),
        ("destination-a", "home-b"),
    }
    assert [(row["from_id"], row["to_id"]) for row in transit] == [
        ("destination-a", "home-c")
    ]


def test_first_network_build_does_not_invalidate_its_own_cache(tmp_path, monkeypatch):
    network = tmp_path / "network"
    network.mkdir()
    (network / "streets.osm.pbf").write_bytes(b"public streets fixture")
    config = _config(network)
    config["people"] = config["people"][:1]
    config["people"][0]["modes"] = ["walk"]
    config["routing"]["cache"] = True
    listings = [{"id": "home", "lat": 41.89, "lon": -87.62}]
    calls = 0

    def building_engine(**kwargs):
        nonlocal calls
        calls += 1
        (network / "network.dat").write_bytes(b"new derived graph")
        (network / "network_settings.json").write_text('{"r5r_version":"fixture"}')
        return _fake_engine(**kwargs)

    monkeypatch.setattr(routing, "_execute_r5r", building_engine)
    first = routing.compute_routes(listings, config, tmp_path / "routes")
    assert routing.routes_match(listings, config, first)
    second = routing.compute_routes(listings, config, tmp_path / "routes")
    assert second["cache"]["hit"] is True
    assert calls == 1
