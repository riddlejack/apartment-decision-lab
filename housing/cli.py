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
from .store import Store, export_csv, read_listings


def print_json(value, *, file=None):
    print(json.dumps(value, indent=2, allow_nan=False), file=file or sys.stdout)


def state(store):
    config = load_config(store.workspace)
    listings = store.listings()
    path = store.workspace / "routes.json"
    routes = json.loads(path.read_text()) if path.exists() else {"results": [], "status": "not_run"}
    rankings = []
    if routes.get("results"):
        from .routing import rank_listings, routes_match
        if routes_match(listings, config, routes):
            rankings = rank_listings(listings, config.get("people", []), routes)
        else:
            routes = {"results": [], "status": "stale", "message": "Origins or routing configuration changed. Run housing route again."}
    return {"listings": listings, "config": config, "routes": routes, "rankings": rankings, "status": store.status()}


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
    sources = load_config(store.workspace).get("sources", [])
    if only and not any(s["id"] == only for s in sources):
        raise ValueError(f"Unknown source: {only}")
    summaries = []
    for source in sources:
        if (only and source["id"] != only) or not source.get("enabled", False):
            continue
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
    no_sources = "No enabled sources. See https://github.com/riddlejack/apartment-decision-lab/blob/main/docs/COLLECTION.md."
    return {"sources": summaries, "message": no_sources if not summaries else "Previous inventory is retained, including after failed or partial runs."}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local apartment research and household commute comparison")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--workspace", type=Path, default=Path(".housing"), help="private data directory (default .housing)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="create an empty private workspace")
    sub.add_parser("demo", help="initialize synthetic listings and an example household")
    sub.add_parser("doctor", help="inspect installation and optional routing tools")
    p = sub.add_parser("import", help="import JSON or CSV listings")
    p.add_argument("path", type=Path)
    p = sub.add_parser("geocode", help="explicitly send one US address to the US Census geocoder")
    p.add_argument("address", help="US street address; sent to geocoding.geo.census.gov")
    for name in ("collect", "refresh"):
        p = sub.add_parser(name, help="bounded collection from enabled sources")
        p.add_argument("--source")
    p = sub.add_parser("sources", help="inspect configured sources without fetching")
    p.add_argument("action", nargs="?", choices=["check"], default="check")
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
                                    "note": "Optional. See https://github.com/riddlejack/apartment-decision-lab/blob/main/docs/ROUTING.md; executable presence is not engine validation."},
                        "core": "No Node, Java, R, API key or LLM needed for import, comparison and export."})
            return 0
        workspace = args.workspace.expanduser().resolve()
        if args.command not in ("init", "demo"):
            # Read-only and operational commands should not create a database
            # merely because an uninitialized workspace path was mistyped.
            load_config(workspace)
        store = Store(workspace)
        if args.command in ("init", "demo"):
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
            print_json({"workspace": str(store.workspace), **summary, "next": "housing review (with the same --workspace, if customized)"})
        elif args.command == "import":
            load_config(store.workspace)
            print_json(store.import_rows(read_listings(args.path)))
        elif args.command == "geocode":
            from .geocode import geocode_address
            print_json(geocode_address(args.address, store.workspace / "geocodes"))
        elif args.command in ("collect", "refresh"):
            result = collect(store, args.source)
            print_json(result)
            return 1 if any(s["status"] in ("error", "blocked") for s in result["sources"]) else 0
        elif args.command == "sources":
            config = load_config(store.workspace)
            print_json({"sources": config.get("sources", []), "network_requests": 0, "note": "Configuration check only; collect performs a bounded live fetch."})
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
