"""The same bounded commands serve humans and coding agents."""
from __future__ import annotations

import argparse
import importlib.resources
import json
import os
import shutil
import sys
from pathlib import Path

from . import __version__
from .config import default_config, load_config, save_config
from .store import Store, export_csv, read_listings, duplicate_groups


def print_json(value, *, file=None):
    print(json.dumps(value, indent=2, allow_nan=False), file=file or sys.stdout)


def state(store):
    config = load_config(store.workspace)
    listings = store.review_listings()
    path = store.workspace / "routes.json"
    routes = json.loads(path.read_text()) if path.exists() else {"results": [], "status": "not_run"}
    rankings = []
    if routes.get("results"):
        from .routing import rank_listings, routes_match
        if routes_match(listings, config, routes):
            rankings = rank_listings(listings, config.get("people", []), routes)
        else:
            routes = {"results": [], "status": "stale", "message": "Origins or routing configuration changed. Run goldblum route again."}
    from .search import assess, summarize
    for listing in listings:
        listing["search"] = assess(listing, config.get("search", {}))
    from .sources import source_catalog
    from .assisted import plan
    return {"listings": listings, "config": config, "routes": routes, "rankings": rankings, "status": store.status(),
            "search_summary": summarize(listings, config.get("search", {})),
            "duplicate_groups": duplicate_groups(listings), "source_catalog": source_catalog(config.get("city", "Chicago")),
            "collection_plan": plan(store)}


def setup(store, city, search, include_sources=True):
    from .sources import default_sources
    config = load_config(store.workspace)
    config["city"] = city
    from .search import validate_search
    config["search"] = validate_search(search)
    if include_sources:
        defaults = default_sources(city, search)
        # Retain operator-added sources. Catalog entries are rebuilt for the new query.
        generated = {s["id"] for s in defaults}
        custom = [s for s in config.get("sources", []) if s["id"] not in generated and not s.get("catalog_source")]
        config["sources"] = defaults + custom
    save_config(store.workspace, config)
    return {"saved": True, "config": config}


def geocode_listings(store, limit=25):
    from .geocode import geocode_address
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("Geocode limit must be between 1 and 100")
    config = load_config(store.workspace)
    updated, unresolved, lookups = [], [], {}
    for row in store.listings():
        if row.get("lat") is not None or not row.get("address"):
            continue
        address = row["address"]
        if config.get("city") and config["city"].lower() not in address.lower():
            address += ", " + config["city"]
        if address not in lookups:
            if len(lookups) >= limit:
                break
            try:
                lookups[address] = geocode_address(address, store.workspace / "geocodes").get("matches", [])
            except (ValueError, RuntimeError, OSError) as exc:
                lookups[address] = []
                unresolved.append({"id": row["id"], "reason": str(exc)})
        matches = lookups[address]
        if len(matches) == 1:
            row.update(lat=matches[0]["lat"], lon=matches[0]["lon"])
            updated.append(row)
        else:
            unresolved.append({"id": row["id"], "reason": "No unique address match"})
    if updated:
        store.import_rows(updated)
    return {"provider": "US Census", "addresses_checked": len(lookups), "listings_updated": len(updated),
            "unresolved": unresolved, "note": "Estimated address locations; review map before routing."}


def route(store):
    from .routing import compute_routes
    payload = compute_routes(store.listings(), load_config(store.workspace), store.workspace / "routing")
    path = store.workspace / "routes.json"
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n")
    if os.name == "posix":
        temp.chmod(0o600)
    temp.replace(path)
    return payload


def collect(store, only=None):
    from .collectors import collect_source
    config = load_config(store.workspace)
    sources = config.get("sources", [])
    if only and not any(s["id"] == only for s in sources):
        raise ValueError(f"Unknown source: {only}")
    summaries = []
    for source in sources:
        if (only and source["id"] != only) or not source.get("enabled", False):
            continue
        source = {**source, "search": {**source.get("search", {}), **config.get("search", {})}}
        result = collect_source(source)
        rows = result.get("listings", [])
        # Import transaction validates all rows before writing any observation.
        try:
            imported = store.import_rows(rows) if rows else {"observations_added": 0}
        except ValueError as exc:
            result = {"status": "error", "message": f"Invalid adapter output: {exc}", "requests": result.get("requests", 0), "listings": []}
            imported = {"observations_added": 0}
        store.record_run(source["id"], result)
        summaries.append({"source": source["id"], **{k: v for k, v in result.items() if k != "listings"}, **imported})
    no_sources = "No enabled sources. See https://github.com/riddlejack/goldblum/blob/main/docs/COLLECTION.md."
    return {"sources": summaries, "message": no_sources if not summaries else "Previous inventory is retained, including after failed or partial runs."}


def default_workspace():
    """Prefer Goldblum, while keeping existing searches usable without a move."""
    current = Path(".goldblum")
    legacy = Path(".housing")
    if not (current / "config.json").exists() and (legacy / "config.json").exists():
        return legacy
    return current


def main(argv=None):
    parser = argparse.ArgumentParser(description="Goldblum: find apartments and compare roommate commutes")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--workspace", type=Path, default=default_workspace(), help="private data directory (default .goldblum; existing .housing reused)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="create an empty private workspace")
    sub.add_parser("demo", help="initialize synthetic listings and an example household")
    p = sub.add_parser("start", help="open your search; create a private workspace if needed")
    p.add_argument("--city", default=None)
    p.add_argument("--port", type=int, default=8765)
    p = sub.add_parser("setup", help="save search requirements and select city sources")
    p.add_argument("--city", default="Chicago")
    p.add_argument("--residents", type=int, default=1)
    p.add_argument("--budget-per-person", type=float)
    p.add_argument("--max-rent", type=float)
    p.add_argument("--bedrooms", type=float)
    p.add_argument("--bathrooms", type=float)
    p.add_argument("--sqft", type=float)
    p.add_argument("--move-in")
    sub.add_parser("doctor", help="inspect installation and optional routing tools")
    p = sub.add_parser("network", help="preview or download public Chicago routing inputs")
    p.add_argument("--city")
    p.add_argument("--download", action="store_true")
    p.add_argument("--refresh", action="store_true", help="replace existing inputs and rebuild the derived graph next run")
    p = sub.add_parser("import", help="import JSON or CSV listings")
    p.add_argument("path", type=Path)
    p = sub.add_parser("geocode", help="explicitly send one US address to the US Census geocoder")
    p.add_argument("address", help="US street address; sent to geocoding.geo.census.gov")
    p = sub.add_parser("geocode-listings", help="look up missing listing coordinates with US Census")
    p.add_argument("--limit", type=int, default=25)
    for name in ("collect", "refresh"):
        p = sub.add_parser(name, help="bounded collection from enabled sources")
        p.add_argument("--source")
    p = sub.add_parser("sources", help="inspect configured sources without fetching")
    p.add_argument("action", nargs="?", choices=["check", "catalog"], default="check")
    p = sub.add_parser("assisted", help="plan browser work, extract batches, and import captures")
    assisted = p.add_subparsers(dest="assisted_command", required=True)
    assisted.add_parser("plan", help="show coverage gaps and saved resume points")
    capture = assisted.add_parser("import", help="import a browser capture and save its progress")
    capture.add_argument("path", type=Path)
    script = assisted.add_parser("script", help="print the read-only DOM batch extractor")
    from .browser import RECIPES
    script.add_argument("--recipe", choices=RECIPES, default="generic")
    script.add_argument("--source", required=True)
    script.add_argument("--search-url", help="original filtered search URL, preserved across pages")
    script.add_argument("--options", type=Path, help="JSON with actual applied criteria, limits, or generic selectors")
    p = sub.add_parser("status", help="compact machine-readable state and review queue")
    p.add_argument("--json", action="store_true", help="JSON is the default")
    sub.add_parser("route", help="compute configured outbound/return commute windows")
    sub.add_parser("compare", help="print complete and incomplete household commute rankings")
    p = sub.add_parser("export", help="export listing facts without household destinations")
    p.add_argument("--format", choices=("json", "csv"), default="csv")
    p.add_argument("--output", type=Path)
    p = sub.add_parser("review", help="serve the bundled interface on 127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            print_json({"version": __version__, "python": sys.version.split()[0], "workspace": str(args.workspace.resolve()),
                        "initialized": (args.workspace / "config.json").exists(),
                        "routing": {"Rscript": bool(shutil.which("Rscript")), "java": bool(shutil.which("java")),
                                    "note": "Optional. See https://github.com/riddlejack/goldblum/blob/main/docs/ROUTING.md; executable presence is not engine validation."},
                        "core": "No Node, Java, R, API key or LLM needed for import, comparison and export."})
            return 0
        workspace = args.workspace.expanduser().resolve()
        if args.command not in ("init", "demo", "start", "setup"):
            # Read-only and operational commands should not create a database
            # merely because an uninitialized workspace path was mistyped.
            load_config(workspace)
        store = Store(workspace)
        if args.command in ("start", "setup"):
            if not (store.workspace / "config.json").exists():
                save_config(store.workspace, default_config())
            if args.command == "setup":
                search = {"residents": args.residents, "budget_per_person": args.budget_per_person,
                          "max_rent": args.max_rent, "min_bedrooms": args.bedrooms if args.bedrooms is not None else args.residents,
                          "min_bathrooms": args.bathrooms, "min_sqft": args.sqft, "move_in_date": args.move_in}
                print_json(setup(store, args.city, search))
            else:
                if args.city:
                    setup(store, args.city, load_config(store.workspace).get("search", {}))
                from .server import serve
                serve(store, args.port)
        elif args.command in ("init", "demo"):
            if (store.workspace / "config.json").exists():
                raise ValueError("Workspace already initialized; choose --workspace NEW_DIRECTORY to preserve existing data")
            if args.command == "demo":
                resources = importlib.resources.files("housing").joinpath("examples")
                save_config(store.workspace, json.loads(resources.joinpath("household.json").read_text()))
                summary = store.import_rows(json.loads(resources.joinpath("listings.json").read_text()))
                (store.workspace / "routes.json").write_text(resources.joinpath("routes.json").read_text())
            else:
                save_config(store.workspace, default_config())
                summary = {"listings": 0}
            print_json({"workspace": str(store.workspace), **summary, "next": "goldblum review (with the same --workspace, if customized)"})
        elif args.command == "import":
            load_config(store.workspace)
            print_json(store.import_rows(read_listings(args.path)))
        elif args.command == "geocode":
            from .geocode import geocode_address
            print_json(geocode_address(args.address, store.workspace / "geocodes"))
        elif args.command == "geocode-listings":
            print_json(geocode_listings(store, args.limit))
        elif args.command == "network":
            from .network import prepare
            print_json(prepare(store.workspace, load_config(store.workspace), download=args.download,
                               refresh=args.refresh, city=args.city))
        elif args.command in ("collect", "refresh"):
            result = collect(store, args.source)
            print_json(result)
            return 1 if any(s["status"] in ("error", "blocked", "unimplemented") for s in result["sources"]) else 0
        elif args.command == "assisted":
            from .assisted import plan, ingest
            if args.assisted_command == "plan":
                print_json(plan(store))
            elif args.assisted_command == "import":
                print_json(ingest(store, args.path))
            else:
                from .browser import extraction_script
                from .sources import source_catalog
                config = load_config(store.workspace)
                sources = {s["id"]: s for s in source_catalog(config.get("city", "Chicago"))}
                for source in config.get("sources", []):
                    sources[source["id"]] = {**sources.get(source["id"], {}), **source}
                options = dict(sources.get(args.source, {}).get("browser_options", {}))
                if args.options:
                    supplied = json.loads(args.options.read_text())
                    if not isinstance(supplied, dict):
                        raise ValueError("Browser options must be a JSON object")
                    options.update(supplied)
                print(extraction_script(args.source, args.recipe, args.search_url, options))
        elif args.command == "sources":
            config = load_config(store.workspace)
            from .sources import source_catalog
            print_json({"sources": source_catalog(config.get("city", "Chicago")) if args.action == "catalog" else config.get("sources", []), "network_requests": 0, "note": "Configuration only. Run collect for fresh listings."})
        elif args.command == "status":
            load_config(store.workspace)
            print_json(store.status())
        elif args.command == "route":
            result = route(store)
            print_json({k: v for k, v in result.items() if k != "results"} | {"route_rows": len(result.get("results", []))})
        elif args.command == "compare":
            value = state(store)
            print_json({"route_status": value["routes"].get("status"), "rankings": value["rankings"]})
        elif args.command == "export":
            load_config(store.workspace)
            data = export_csv(store.listings()) if args.format == "csv" else json.dumps({"listings": store.listings()}, indent=2) + "\n"
            if args.output:
                args.output.write_text(data)
                print_json({"output": str(args.output.resolve()), "listings": len(store.listings())})
            else:
                print(data, end="")
        elif args.command == "review":
            load_config(store.workspace)
            from .server import serve
            serve(store, args.port)
        return 0
    except (ValueError, OSError, RuntimeError) as exc:
        print_json({"error": str(exc)}, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
