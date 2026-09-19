# Working with Goldblum

Use [current scope and remaining work](docs/NEXT-STEPS.md) when planning changes. Fresh apartment collection is the main product capability.

Use the CLI before inventing scraping or routing workflows. Start with `goldblum doctor` and `goldblum status --json` (or `uv run goldblum ...` in a checkout). `--workspace PATH` goes before the subcommand. Read only the affected adapter/exception; do not load a database or full HTML archive into context.

- Setup: `goldblum start --city Chicago` for intake and collection, or `goldblum setup` for CLI configuration. `goldblum demo` creates a separate example; imports remain optional.
- Refresh: inspect configured sources, run `goldblum collect` / `goldblum refresh`, report source statuses and unresolved facts. For a useful rendered-page gap, follow [browser-assisted collection](docs/BROWSER-COLLECTION.md) and resume `goldblum assisted plan`; verify website filters because saved criteria are not applied automatically.
- Routing: read `docs/ROUTING.md`, configure destinations/modes and valid dated OSM/GTFS inputs, then `goldblum route` and `goldblum compare`. Never invent times or treat a missing route as zero.
- Repair: retain a small failing fixture, fix its parser, test offline, then perform one permitted bounded probe. A browser is an optional capability, not an assumed requirement or a way around blocked access.
- Test: `uv run pytest`; build with `uv build`. The wheel contains the web interface.

Household config, downloaded networks, raw evidence, route matrices, and local database stay private. `.goldblum/` is ignored; any other workspace needs its own exclusion. Do not commit real destinations, scraped archives, credentials, messages, or personal notes. Only synthetic or explicitly cleared fixtures belong in tests/examples.

Distinguish synthetic, historical, observed, and modeled results. Source-scoped identities are conservative; no automatic cross-source unit merge. A failed/partial fetch never retires old inventory. Report coverage gaps instead of claiming every apartment in a city. Keep driving's traffic/parking limitations and scheduled transit's non-reliability interpretation visible.
