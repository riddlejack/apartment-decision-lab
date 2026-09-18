# Apartment Decision Lab

Compare apartments around the people who will live in them: their destinations, schedules, transportation options, budget, and tolerance for a long commute.

A local-first research tool extracted from a Chicago apartment search. It collects or imports listing facts, preserves observations, models household commutes, and opens a comparison interface. Routine operations require **no AI model, API key, Node, or hosted account**. Codex and Claude Code can operate the same commands.

**Early release.** The bundled eight listings are invented demonstration data, not available apartments. Their sample commute times were genuinely computed with R5, OSM and July 21, 2026 transit schedules for unrelated civic destinations. They are historical model outputs, not current predictions. This is a focused tool, not an exhaustive listing service. Source coverage and route availability are explicit.

## Try it

With Python 3.11+ and [uv](https://docs.astral.sh/uv/getting-started/installation/):

```sh
uv tool install git+https://github.com/riddlejack/apartment-decision-lab
housing demo
housing review
```

Open **http://127.0.0.1:8765**. Demo initialization refuses to overwrite an existing workspace. For a separate example use `housing --workspace demo-search demo`, then `housing --workspace demo-search review`.

Alternatively, install the GitHub release wheel into a Python virtual environment with `pip install <wheel-file>`. The interface is included in the wheel; no frontend build is necessary.

## Five useful capabilities

1. **Collect or import.** Shared property-manager adapters plus JSON/CSV import; fetching is bounded and independent from parsing.
2. **Keep evidence and unknowns.** Source-scoped identities and dated observations preserve changes without merging different units. Missing rent or bathrooms remain unknown.
3. **Model household commutes.** Optional local OSM/GTFS routing supports walking, biking, walking plus scheduled transit, and explicitly enabled free-flow driving. Each person has their own destinations and allowed modes. Outbound and return trips are calculated separately.
4. **Compare tradeoffs.** Filter listing facts, inspect per-person times, and compare mean weekly travel with the worst person's commute and individual caps.
5. **Export and reproduce.** Download listing facts as CSV/JSON. Keep your household and route cache private. Repeat the same commands without an agent rediscovering the workflow.

The routing engine is optional because street graphs and transit feeds are substantially heavier than the rest of the app. The demo's precomputed results let you explore rankings without installing it. Changing frequencies or commute caps reranks those times locally; changing destinations, modes or scenarios requires recalculation. See [routing setup and model limits](docs/ROUTING.md). The app does not substitute straight-line guesses when routing is unavailable. Driving is not traffic-aware; park-and-ride and shared-car scheduling are not implemented.

## Start a real search

```sh
housing --workspace my-search init
housing --workspace my-search import listings.csv
housing --workspace my-search review
housing --workspace my-search status --json
housing --workspace my-search export --format csv --output apartments.csv
```

The workspace contains `config.json`, `housing.sqlite`, and optional routing cache/results. Use the household editor for private destinations and allowed modes; use configuration for source URLs and the optional routing network. Enter coordinates directly, or explicitly look up an address with the **US Census** button. Address lookup sends that address to the Census service; it is never triggered automatically when saving a household. Census locations are estimated along address ranges, so review the match before routing. [Official geocoder documentation](https://geocoding.geo.census.gov/geocoder/Geocoding_Services_API.html)

**Keep real workspaces outside the repository or in its ignored `.housing/` directory.** Custom directories such as `my-search/` are not automatically ignored by Git. Exports can contain your imported listing notes; review them before sharing.

Import fields: `source`, `source_id` (or `id`), `title`, `address`, `unit`, `grain`, `rent`, `total_monthly_cost`, `bedrooms`, `bathrooms`, `lat`, `lon`, `url`, `observed_at`, `historical`, `synthetic`, `notes`. Only identity is required; missing facts remain null. Rent is monthly USD gross base rent, not net promotional rent; a provider's total monthly price including fees is stored separately. `grain` is `unit`, `floorplan`, `property`, or `unknown`. `observed_at` is an ISO timestamp with timezone; omitted timestamps mean import time, not source verification time. Historical imports should include their original capture timestamps and `historical: true`.

CSV export prefixes cells that spreadsheet software could interpret as formulas. Use JSON export when exact preservation of provider text is more important than opening the file directly in a spreadsheet.

```sh
# After configuring permitted sources in config.json:
housing sources check
housing collect
housing refresh

# After installing optional routing dependencies and configuring fresh feeds:
housing route
housing compare
```

`refresh` is a bounded re-fetch of the configured source pages, not an unlimited city crawl. Failed or partial collection preserves existing observations. Absence from a page never automatically makes a listing unavailable. See [collection support and limitations](docs/COLLECTION.md).

## With Codex or Claude Code

Clone this repository and ask the agent to set up a search. [AGENTS.md](AGENTS.md) contains the short operating contract; `CLAUDE.md` imports it. The included setup, refresh, and source-repair skills direct agents to compact JSON summaries and targeted exceptions. No custom MCP server or vendor-specific API is necessary. Browser assistance is optional and depends on capabilities in your agent environment.

## Development

```sh
git clone https://github.com/riddlejack/apartment-decision-lab.git
cd apartment-decision-lab
uv sync --locked
uv run pytest
uv run housing demo
uv run housing review
uv build
```

The Python package, SQLite store, and static interface are deliberately small. No service fleet, authentication database, or cloud deployment is required. [Architecture and scope](docs/ARCHITECTURE.md) explains the boundaries. [The Chicago case study](docs/CASE-STUDY.md) distinguishes the original research from what this release actually reproduces.

Code and invented examples are MIT licensed. Third-party listing content, OSM, GTFS, and routing dependencies retain their own licenses and terms. Original private household data, conversation records, destination matrices, and raw collection archives are not included.
