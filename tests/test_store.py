import json
import os
from copy import deepcopy

import pytest

from housing.config import default_config, save_config
from housing.store import Store, export_csv, validate_listing


def row(**changes):
    return {"source": "manager", "source_id": "123", "rent": 2000, "bedrooms": 3,
            "grain": "unit", "observed_at": "2026-07-01T12:00:00Z", **changes}


def test_source_identity_does_not_merge_units_or_sources(tmp_path):
    store = Store(tmp_path)
    if os.name == "posix":
        assert store.path.stat().st_mode & 0o777 == 0o600
    store.import_rows([row(), row(source="other"), row(source_id="124")])
    assert len(store.listings()) == 3


def test_later_observation_wins_not_import_order_and_reimport_is_idempotent(tmp_path):
    store = Store(tmp_path)
    store.import_rows([row(rent=2100, observed_at="2026-08-01T12:00:00Z")])
    store.import_rows([row()])
    assert store.import_rows([row()])["observations_added"] == 0
    assert store.listings()[0]["rent"] == 2100
    assert store.status()["observations"] == 2


def test_same_timestamp_uses_latest_import_as_deterministic_tiebreaker(tmp_path):
    store = Store(tmp_path)
    store.import_rows([row(rent=2000), row(rent=2050)])
    assert store.listings()[0]["rent"] == 2050


def test_import_is_atomic_and_missing_is_not_zero(tmp_path):
    store = Store(tmp_path)
    with pytest.raises(ValueError):
        store.import_rows([row(), row(source_id="124", lat=float("nan"), lon=0)])
    assert store.listings() == []
    store.import_rows([row(bathrooms=None)])
    assert store.listings()[0]["bathrooms"] is None


def test_failed_run_does_not_retire_inventory(tmp_path):
    store = Store(tmp_path)
    store.import_rows([row()])
    store.record_run("manager", {"status": "blocked", "message": "429", "listings": []})
    assert len(store.listings()) == 1
    assert store.status()["recent_runs"][0]["status"] == "blocked"


def test_dangerous_urls_and_spreadsheet_formulas(tmp_path):
    store = Store(tmp_path)
    with pytest.raises(ValueError):
        store.import_rows([row(url="javascript:alert(1)")])
    store.import_rows([row(title="=1+1")])
    assert "'=1+1" in export_csv(store.listings())


def test_config_rejects_missing_destination_coordinates_and_keeps_old_file(tmp_path):
    config = default_config()
    save_config(tmp_path, config)
    broken = deepcopy(config)
    broken["people"] = [{"id": "a", "modes": ["transit"], "destinations": [{"id": "d", "lat": None}]}]
    with pytest.raises(ValueError):
        save_config(tmp_path, broken)
    assert json.loads((tmp_path / "config.json").read_text()) == config


def test_csv_export_roundtrip_preserves_stable_identity(tmp_path):
    from housing.store import read_listings
    store = Store(tmp_path / "one")
    store.import_rows([row()])
    path = tmp_path / "listings.csv"
    path.write_text(export_csv(store.listings()))
    other = Store(tmp_path / "two")
    other.import_rows(read_listings(path))
    assert other.listings() == store.listings()


def test_json_export_shape_roundtrips_optional_evidence_fields(tmp_path):
    from housing.store import read_listings

    original = Store(tmp_path / "one")
    original.import_rows([row(
        total_monthly_cost=2075,
        parser_version="json-feed-v1",
        source_content_sha256="a" * 64,
        historical=True,
    )])
    path = tmp_path / "listings.json"
    path.write_text(json.dumps({"listings": original.listings()}))
    restored = Store(tmp_path / "two")
    restored.import_rows(read_listings(path))
    assert restored.listings() == original.listings()


def test_identity_is_composed_after_normalization_and_long_ids_are_rejected():
    normalized = validate_listing(row(source=" manager ", source_id=" unit-1 "))
    assert normalized["source"] == "manager"
    assert normalized["source_id"] == "unit-1"
    assert normalized["id"] == "manager:unit-1"
    with pytest.raises(ValueError, match="1000 characters"):
        validate_listing(row(source_id="x" * 1001))


def test_booleans_are_not_numeric_listing_or_destination_values(tmp_path):
    with pytest.raises(ValueError, match="rent must be numeric"):
        validate_listing(row(rent=True))
    config = default_config()
    config["people"] = [{
        "id": "person",
        "modes": ["walk"],
        "destinations": [{"id": "destination", "lat": True, "lon": -93.2, "days_per_week": 2}],
    }]
    with pytest.raises(ValueError, match="Destination lat"):
        save_config(tmp_path, config)
    with pytest.raises(ValueError, match="historical must be boolean"):
        validate_listing(row(historical=2))
    with pytest.raises(ValueError, match="source and source_id must be strings"):
        validate_listing(row(source_id=True))


def test_config_rejects_incomplete_or_credentialed_sources(tmp_path):
    config = default_config()
    config["sources"] = [{"id": "bad", "adapter": "json", "url": "https://user:secret@example.test/feed", "enabled": False}]
    with pytest.raises(ValueError, match="without credentials"):
        save_config(tmp_path, config)


def test_uninitialized_status_has_nonzero_exit_without_creating_workspace(tmp_path, capsys):
    from housing.cli import main

    workspace = tmp_path / "mistyped-workspace"
    assert main(["--workspace", str(workspace), "status"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err)["error"].startswith("Workspace is not initialized")
    assert not workspace.exists()
