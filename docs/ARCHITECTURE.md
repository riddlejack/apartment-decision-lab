# One local pipeline

```text
JSON / CSV / configured source page
  -> validated, source-scoped listing observation
  -> SQLite append-only history and latest-observation projection
  -> optional OSM + GTFS route computation and cache
  -> household comparison in the local web interface
  -> CSV / JSON listing export
```

`search.py` owns saved requirements and three-way matching: matching, excluded, or needs checking. `sources.py` reads city catalogs; unknown cities can use custom source configurations. `network.py` downloads public Chicago routing inputs on request. `store.py` owns validation, observation persistence, private shortlist notes and exports. `collectors.py` owns fetching and parsing. `routing.py` owns route requests, cache validation and household ranking. `cli.py` composes those capabilities; `server.py` exposes the same operations on loopback. `web/` is a small bundled interface with no build system.

Listing IDs are namespaced by source. Identical imports with identical timestamps are idempotent. Later captures append observations; current state selects the latest observed timestamp. Importing an older snapshot cannot overwrite a newer observation. Different units and sources are not automatically merged. A price change is an observation, not a new apartment. Provider ID reuse and ambiguous duplicates still require review.

Unknown values remain null. Property/floorplan/unit grain is preserved and exposed. Collection errors and review counts are machine-readable. Source page omissions do not prove unavailability. This intentionally favors visible uncertainty over false completeness.

Routing is separate from listing acquisition and preferences. Cached numerical routes can be reused; changed origins, destinations, departure settings or network inputs must invalidate their relevant results. Ranking keeps per-person constraints and incomplete coverage visible. Weekly totals use user-supplied destination frequencies, not an assumed five-day office week.

## Current limits

- USD listings. Explicit coordinates work globally; optional user-triggered Census address lookup is US-specific.
- Supported property-manager pages and file imports; no universal scraper or ongoing citywide coverage guarantee.
- Conservative source identity; no fuzzy entity-resolution service.
- Local use only, without logins, cross-device synchronization, accounts or alerts.
- Optional r5r routing environment; explicit Chicago network downloads, but no hosted route API.
- Departure scenarios only; no guarantee of arrival by a deadline, no empirical transit delay prediction, no traffic-aware driving.
- No claim that Windows or every transit network has been validated merely because Python installs there.

New cities should require configuration and source/OSM/GTFS inputs, not edits to household logic. A shared parser's existence does not establish collection coverage in another city. A second-city integration should be verified before advertising city support.

## Hosting later

The smallest public web presence is a static portfolio case study with invented examples and downloadable releases. A continuous Chicago listing service adds source maintenance, feed freshness, monitoring and operational cost. Accounts add custody of private destinations. Neither is necessary to make the repository useful, and this release does not silently deploy either.
