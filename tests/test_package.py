import json
from importlib.resources import files
from pathlib import Path


def test_examples_are_explicitly_synthetic():
    rows = json.loads(files("housing").joinpath("examples/listings.json").read_text())
    assert rows and all(row["synthetic"] and row["historical"] for row in rows)
    assert files("housing").joinpath("web/index.html").is_file()
    assert files("housing").joinpath("r5r_runner.R").is_file()


def test_agent_skills_do_not_drift_between_clients():
    root = Path(__file__).parents[1]
    for source in (root / ".agents/skills").glob("*/SKILL.md"):
        assert source.read_bytes() == (root / ".claude/skills" / source.parent.name / "SKILL.md").read_bytes()


def test_default_workspace_preserves_legacy_search_and_prefers_initialized_goldblum(tmp_path, monkeypatch):
    from housing.cli import main
    from housing.config import load_config, save_config
    monkeypatch.chdir(tmp_path)
    assert main(["--workspace", ".housing", "init"]) == 0
    config = load_config(tmp_path / ".housing")
    config["city"] = "Legacy city"
    save_config(tmp_path / ".housing", config)
    assert main(["status"]) == 0
    assert not (tmp_path / ".goldblum").exists()
    assert load_config(tmp_path / ".housing")["city"] == "Legacy city"
    assert main(["--workspace", ".goldblum", "init"]) == 0
    from housing.cli import default_workspace
    assert default_workspace() == Path(".goldblum")


def test_fresh_default_workspace_uses_goldblum(tmp_path, monkeypatch):
    from housing.cli import main
    monkeypatch.chdir(tmp_path)
    assert main(["init"]) == 0
    assert (tmp_path / ".goldblum" / "config.json").is_file()
    assert not (tmp_path / ".housing").exists()


def test_bundled_routes_match_demo_and_reject_destination_changes():
    from housing.routing import rank_listings, routes_match
    from housing.store import validate_listing
    examples = files("housing").joinpath("examples")
    rows = [validate_listing(row) for row in json.loads(examples.joinpath("listings.json").read_text())]
    config = json.loads(examples.joinpath("household.json").read_text())
    routes = json.loads(examples.joinpath("routes.json").read_text())
    assert routes["demo"] is True and routes_match(rows, config, routes)
    ranks = rank_listings(rows, config["people"], routes)
    assert len(ranks) == 8 and all(rank["complete"] for rank in ranks)
    config["people"][0]["max_minutes"] = 10
    assert routes_match(rows, config, routes)  # Preferences rerank without network work.
    config["people"][0]["destinations"][0]["lat"] += 0.1
    assert not routes_match(rows, config, routes)
