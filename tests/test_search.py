import csv
import io
import pytest
from housing.search import assess, validate_search
from housing.store import Store, duplicate_groups, export_csv, validate_listing


def test_unknown_size_is_pending_but_known_mismatch_is_excluded():
    search = validate_search({"residents": 3, "budget_per_person": 1000, "min_bedrooms": 3, "min_sqft": 1200})
    assert search["max_rent"] == 3000
    row = {"rent": 2900, "bedrooms": 3, "sqft": None}
    assert assess(row, search) == {"eligible": True, "excluded": [], "needs_check": ["sqft"]}
    row["sqft"] = 900
    assert assess(row, search)["excluded"] == ["sqft"]
    with pytest.raises(ValueError):
        validate_search({"residents": 0})


def test_extended_facts_csv_roundtrip():
    row = validate_listing({"id": "a", "sqft": 1400, "pets": False, "parking": True,
                            "amenities": ["Laundry", "Balcony"], "monthly_fees": 45})
    parsed = validate_listing(next(csv.DictReader(io.StringIO(export_csv([row])))))
    for field in ("sqft", "pets", "parking", "amenities", "monthly_fees"):
        assert parsed[field] == row[field]


def test_refresh_changes_and_private_notes_survive(tmp_path):
    store = Store(tmp_path)
    row = {"id": "a", "rent": 2500, "observed_at": "2026-07-01T00:00:00Z"}
    store.import_rows([row])
    store.annotate("import:a", "shortlist", "Private tour notes")
    store.import_rows([{**row, "rent": 2400, "observed_at": "2026-07-02T00:00:00Z"}])
    current = store.review_listings()[0]
    assert current["annotation"]["status"] == "shortlist"
    assert current["change"]["kind"] == "changed"
    assert current["change"]["previous_rent"] == 2500
    assert "Private tour notes" not in export_csv(store.listings())
    store.import_rows([{**row, "rent": 2400, "observed_at": "2026-07-03T00:00:00Z"}])
    assert store.review_listings()[0]["change"]["kind"] == "unchanged"


def test_duplicate_suggestions_do_not_merge_other_units():
    a = {"id": "one:a", "grain": "unit", "address": "1 Example St", "unit": "2A"}
    rows = [a, {**a, "id": "two:b"}, {**a, "id": "three:c", "unit": "2B"},
            {**a, "id": "four:d", "unit": None}]
    assert duplicate_groups(rows) == [["one:a", "two:b"]]
