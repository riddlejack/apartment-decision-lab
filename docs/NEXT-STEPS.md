# Scope and remaining work

Room & Route helps roommates find apartments across sources and compare rent, space, and commutes. Chicago is the first supported source catalog. The demo stays frozen; users refresh their own searches.

## Current v0.3 status

- Search intake, reusable HTTP collectors, saved requirements, and command-line or in-app refresh.
- A Chicago source catalog with runnable sources and visible assisted/blocked gaps. Other cities can use custom source URLs and the same adapters.
- Browser-assisted batch capture, validated imports, a private coverage ledger, and resume points for public rendered pages. One bounded live pass imported 162 source-scoped records: RentCafe 22 unique records from 25 cards, Apartments.com 40, Compass 41, Domu 18, Zillow 9, Apartment List 20, and Baird's Boom embed 12. The UI saved seven resume points and classified 105 records as matching or needing review under example filters of 3 bedrooms, 2 bathrooms, and $4,200 maximum rent. These are records across sources, not unique apartments or city coverage; Zillow was explicitly lazy-load partial.
- Rent, beds, baths, square footage, availability, pets/parking, known costs, map, shortlist and private notes.
- Source-scoped listing history, price changes, conservative duplicate suggestions, CSV/JSON exports.
- Optional local multimodal commute calculations; separate outbound/return scenarios, per-person caps and weekly household comparison.
- Explicit Chicago street/transit downloads, CPU/memory limits, shared work for identical coordinates, and reuse of unchanged origins.

See [collection](COLLECTION.md) for the tested source set and [routing](ROUTING.md) for setup and model limits. A working parser does not establish full market coverage.

## Still open

1. **Broader reliable coverage.** Browser recipes require an agent or user-controlled browser and do not guarantee token-free refresh. Baird's verified generic extraction reports numeric rent, beds, baths, and square feet, but its results mix Chicago-area cities and need explicit geography review plus manual pagination. POST Chicago's Entrata floorplans are accessible rather than blocked, but the page repeats carousel floorplans, mixes per-bed coliving ranges such as `$1,414 to $1,939` with separate full-unit offers, and lacks a verified recipe that preserves price scope and availability grain. SabbaticalHomes still returns human verification to ordinary requests. HomeHarvest/Realtor remains optional and subject to upstream access failure, not proven incremental coverage.
2. **Another city's verified catalog.** Adapters are reusable; a new city's source selection, geography and transit inputs still need validation. No nationwide coverage claim.
3. **Typical traffic-aware driving.** R5 driving is uncongested. Free Chicago traffic observations have road, date and licensing gaps; no blanket multiplier or false rush-hour estimate. Paid providers remain optional candidates, not a requirement or an activated service.
4. **Arrival deadlines and richer time sampling.** Current times are departure scenarios. A departure-time route is not an arrival-by guarantee. Transit estimates use schedules, not measured reliability.

No citywide completeness percentage is defensible without a denominator. Unknown required details stay in review. Commute suitability comes from route time, never straight-line distance around a workplace.

## Performance evidence

A small real R5 run on the public Porto Alegre sample graph, with one origin and four modes, took 1.84 seconds using a prepared graph. The repeated request took about 0.001 seconds from cache. Adding a second origin took 1.28 seconds and computed one origin while reusing one. This verifies cache behavior; it is not a city-scale benchmark or a cold graph-build timing.

The Chicago download command retrieved a roughly 102 MB OSM extract and current CTA, Metra and Pace ZIP files in a bounded setup check. Data remains in a private temporary workspace, not the repository. A city-sized street extract does not cover every suburb.

## Keep it small

Routine HTTP refresh runs without LLM calls. Browser-assisted refresh is targeted gap work and requires an agent or user browser; it has no token-free guarantee. Resume saved pages instead of browsing every listing on every run. Validate changes with focused offline tests, a small live adapter sample when needed, and an installed-app check. Do not refresh the whole city merely to test software.

Defer hosting, accounts, shared-car coordination, live navigation, tours, social/crime scoring, and always-on scheduling. Users can schedule `housing refresh` themselves. Profile R5 before considering a Rust rewrite: Python currently coordinates a Java routing engine.

[Competitor and backend research](FEATURE-RESEARCH.md) records the evidence behind these choices.
