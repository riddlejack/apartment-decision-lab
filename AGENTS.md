# Working with Apartment Decision Lab

Use the CLI before inventing scraping or routing workflows. Start with `housing doctor` and `housing status --json` (or `uv run housing ...` in a checkout). `--workspace PATH` goes before the subcommand. Read only the affected adapter/exception; do not load a database or full HTML archive into context.

- Setup: `housing init` or `housing demo`; import CSV/JSON; `housing review`.
- Refresh: inspect configured sources, run `housing collect` / `housing refresh`, report source statuses and unresolved facts.
- Routing: read `docs/ROUTING.md`, configure destinations/modes and valid dated OSM/GTFS inputs, then `housing route` and `housing compare`. Never invent times or treat a missing route as zero.
- Repair: retain a small failing fixture, fix its parser, test offline, then perform one permitted bounded probe. A browser is an optional capability, not an assumed requirement or a way around blocked access.
- Test: `uv run pytest`; build with `uv build`. The wheel contains the web interface.

Household config, downloaded networks, raw evidence, route matrices, and local database stay private. `.housing/` is ignored; any other workspace needs its own exclusion. Do not commit real destinations, scraped archives, credentials, messages, or personal notes. Only synthetic or explicitly cleared fixtures belong in tests/examples.

Distinguish synthetic, historical, observed, and modeled results. Source-scoped identities are conservative; no automatic cross-source unit merge. A failed/partial fetch never retires old inventory. Report coverage gaps instead of claiming every apartment in a city. Keep driving's traffic/parking limitations and scheduled transit's non-reliability interpretation visible.
