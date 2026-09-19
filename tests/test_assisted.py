import json

import pytest

from housing.assisted import ingest, plan
from housing.config import default_config, save_config
from housing.store import Store


SEARCH_URL = "https://www.domu.com/chicago/apartments-for-rent"


def workspace(tmp_path, *, sources=None):
    config = default_config()
    config["city"] = "Chicago"
    config["sources"] = sources or []
    save_config(tmp_path, config)
    return Store(tmp_path)


def capture(**changes):
    document = {
        "source": {"id": "domu-assisted"},
        "search_url": SEARCH_URL,
        "observed_at": "2026-09-19T15:00:00-05:00",
        "status": "partial",
        "pages_visited": [SEARCH_URL],
        "next_url": f"{SEARCH_URL}?page=2",
        "evidence_note": "Rendered result cards from the first public search page.",
        "criteria": {"max_rent": 3200, "bedrooms": {"min": 2}},
        "listings": [{
            "source_id": "domu-101",
            "url": "https://www.domu.com/chicago/north-side/units/101",
            "title": "Two bedroom with unknown price",
            "address": "101 Example Avenue, Chicago, IL",
            "grain": "unit",
            "rent": None,
            "bedrooms": 2,
            "bathrooms": None,
        }],
    }
    document.update(changes)
    return document


def test_invalid_capture_is_atomic_before_observations_runs_or_ledger(tmp_path):
    store = workspace(tmp_path)
    store.import_rows([{
        "source": "seed",
        "source_id": "kept",
        "observed_at": "2026-09-18T12:00:00Z",
        "title": "Existing inventory survives",
    }])
    invalid = capture(listings=[
        capture()["listings"][0],
        {
            "source_id": "wrong-origin",
            "url": "https://example.net/listings/2",
            "rent": 1800,
        },
    ])

    with pytest.raises(ValueError, match="declared source origin"):
        ingest(store, invalid)

    assert [row["id"] for row in store.listings()] == ["seed:kept"]
    assert store.status()["recent_runs"] == []
    assert not (tmp_path / "assisted-ledger.json").exists()


def test_partial_capture_creates_resume_plan_and_retains_unknowns(tmp_path):
    store = workspace(tmp_path)

    result = ingest(store, capture())

    assert result == {
        "source": "domu-assisted",
        "status": "partial",
        "method": "browser",
        "scope": "searched_pages_only",
        "city_complete": False,
        "imported": {"received": 1, "observations_added": 1, "listings": 1},
        "progress": {
            "pages_visited": 1,
            "resume_url": f"{SEARCH_URL}?page=2",
            "records_captured": 1,
            "observed_at": "2026-09-19T20:00:00+00:00",
        },
    }
    listing = store.listings()[0]
    assert listing["id"] == "domu-assisted:domu-101"
    assert listing["rent"] is None
    assert listing["bathrooms"] is None
    assert listing["parser_version"] == "browser-assisted-v1"

    coverage = plan(store)
    assert coverage["city_complete"] is False
    assert coverage["execution"] == {
        "network_requests": 0,
        "browser_opened": False,
        "agent_runtime_started": False,
    }
    source = next(item for item in coverage["sources"] if item["source"]["id"] == "domu-assisted")
    assert source["action"] == "resume_browser"
    assert source["priority"] == 0
    assert source["resume_url"] == f"{SEARCH_URL}?page=2"
    assert source["progress"]["pages_visited"] == 1


def test_status_only_failure_preserves_inventory_and_resume_progress(tmp_path):
    store = workspace(tmp_path)
    ingest(store, capture())
    failure = capture(
        observed_at="2026-09-19T15:10:00-05:00",
        status="blocked",
        pages_visited=[],
        listings=[],
        evidence_note="Human verification interrupted the resumed page; no bypass attempted.",
    )

    result = ingest(store, failure)

    assert result["imported"] == {"received": 0, "observations_added": 0, "listings": 1}
    assert result["progress"]["pages_visited"] == 1
    assert result["progress"]["resume_url"] == f"{SEARCH_URL}?page=2"
    assert len(store.listings()) == 1
    latest_run = store.status()["recent_runs"][0]
    assert latest_run["status"] == "blocked"
    assert latest_run["method"] == "browser"
    assert latest_run["observed_at"] == "2026-09-19T20:10:00+00:00"
    source = next(item for item in plan(store)["sources"] if item["source"]["id"] == "domu-assisted")
    assert (source["action"], source["reason"]) == ("resume_browser", "resume_point_available")


def test_completed_resume_accumulates_only_explicit_pages_without_city_claim(tmp_path):
    store = workspace(tmp_path)
    ingest(store, capture())
    second_page = f"{SEARCH_URL}?page=2"

    result = ingest(store, capture(
        observed_at="2026-09-19T15:20:00-05:00",
        search_url=second_page,
        status="complete",
        pages_visited=[second_page],
        next_url=None,
        listings=[],
        evidence_note="The resumed page showed no further next-page control.",
    ))

    assert result["status"] == "complete"
    assert result["scope"] == "searched_pages_only"
    assert result["city_complete"] is False
    assert result["progress"]["pages_visited"] == 2
    assert result["progress"]["resume_url"] is None
    item = next(item for item in plan(store)["sources"] if item["source"]["id"] == "domu-assisted")
    assert (item["action"], item["reason"]) == ("review_later", "searched_pages_scope_complete")
    assert item["progress"]["pages_visited"] == 2
    assert item["progress"]["city_complete"] is False


def test_custom_source_must_be_configured_and_declared_origin_is_enforced(tmp_path):
    custom = {
        "id": "neighborhood-owner-assisted",
        "name": "Neighborhood owner",
        "adapter": "assisted",
        "url": "https://rentals.example.org/available",
        "enabled": False,
        "permission_note": "Public owner availability page for assisted review.",
    }
    store = workspace(tmp_path, sources=[custom])
    document = capture(
        source={
            "id": custom["id"],
            "adapter": "assisted",
            "url": "https://rentals.example.org/search?beds=2",
        },
        search_url="https://rentals.example.org/search?beds=2",
        pages_visited=["https://rentals.example.org/search?beds=2"],
        next_url=None,
        status="complete",
        listings=[{
            "id": f"{custom['id']}:unit-7",
            "url": "https://rentals.example.org/units/7",
            "rent": None,
        }],
    )

    assert ingest(store, document)["imported"]["observations_added"] == 1

    unknown = capture(
        source={"id": "undeclared-custom", "url": "https://other.example/search"},
        search_url="https://other.example/search",
        pages_visited=["https://other.example/search"],
        next_url=None,
        status="complete",
        listings=[],
    )
    with pytest.raises(ValueError, match="add a declared custom source"):
        ingest(store, unknown)


def test_path_input_and_complete_scope_require_explicit_page_evidence(tmp_path):
    store = workspace(tmp_path)
    path = tmp_path / "capture.json"
    path.write_text(json.dumps(capture(status="complete", pages_visited=[], next_url=None)), encoding="utf-8")

    with pytest.raises(ValueError, match="at least one explicitly visited page"):
        ingest(store, path)

    assert store.listings() == []
    assert store.status()["recent_runs"] == []


def test_plan_recognizes_http_success_and_empty_beyond_recent_run_window(tmp_path):
    store = workspace(tmp_path)
    store.record_run("sptrec-appfolio", {
        "status": "success", "message": "parsed configured page", "requests": 2, "listings": [],
    })
    for index in range(21):
        store.record_run(f"irrelevant-{index}", {
            "status": "error", "message": "test history", "requests": 0, "listings": [],
        })
    store.record_run("landmark-appfolio", {
        "status": "empty", "message": "explicit empty state", "requests": 2, "listings": [],
    })
    assert all(run["source"] != "sptrec-appfolio" for run in store.status()["recent_runs"])

    items = {item["source"]["id"]: item for item in plan(store)["sources"]}

    assert (items["sptrec-appfolio"]["action"], items["sptrec-appfolio"]["reason"]) == (
        "none", "latest_http_success",
    )
    assert (items["landmark-appfolio"]["action"], items["landmark-appfolio"]["reason"]) == (
        "none", "latest_http_explicit_empty",
    )
    assert items["domu-assisted"]["source"]["browser_recipe"] == "domu"
