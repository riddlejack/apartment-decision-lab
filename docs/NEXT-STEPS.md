# Scope and remaining work

Room & Route helps roommates find apartments across sources and compare rent, space, and commutes. Chicago is the first supported source catalog. The demo stays frozen; users refresh their own searches.

## In v0.2

- Search intake, reusable collectors, saved requirements, and command-line or in-app refresh.
- A Chicago source catalog with runnable sources and visible assisted/blocked gaps. Other cities can use custom source URLs and the same adapters.
- Rent, beds, baths, square footage, availability, pets/parking, known costs, map, shortlist and private notes.
- Source-scoped listing history, price changes, conservative duplicate suggestions, CSV/JSON exports.
- Optional local multimodal commute calculations; separate outbound/return scenarios, per-person caps and weekly household comparison.
- Explicit Chicago street/transit downloads, CPU/memory limits, shared work for identical coordinates, and reuse of unchanged origins.

See [collection](COLLECTION.md) for the tested source set and [routing](ROUTING.md) for setup and model limits. A working parser does not establish full market coverage.

## Still open

1. **Broader reliable coverage.** Add sources only when they contribute relevant units. Some major portals need assisted review; a bounded crawl is not a completeness guarantee. Compare an optional provider against the same criteria and capture period before paying for it.
2. **Another city's verified catalog.** Adapters are reusable; a new city's source selection, geography and transit inputs still need validation. No nationwide coverage claim.
3. **Typical traffic-aware driving.** R5 driving is uncongested. Free Chicago traffic observations have road, date and licensing gaps; no blanket multiplier or false rush-hour estimate. Paid providers remain optional candidates, not a requirement or an activated service.
4. **Arrival deadlines and richer time sampling.** Current times are departure scenarios. A departure-time route is not an arrival-by guarantee. Transit estimates use schedules, not measured reliability.

No citywide completeness percentage is defensible without a denominator. Unknown required details stay in review. Commute suitability comes from route time, never straight-line distance around a workplace.

## Performance evidence

A small real R5 run on the public Porto Alegre sample graph, with one origin and four modes, took 1.84 seconds using a prepared graph. The repeated request took about 0.001 seconds from cache. Adding a second origin took 1.28 seconds and computed one origin while reusing one. This verifies cache behavior; it is not a city-scale benchmark or a cold graph-build timing.

The Chicago download command retrieved a roughly 102 MB OSM extract and current CTA, Metra and Pace ZIP files in a bounded setup check. Data remains in a private temporary workspace, not the repository. A city-sized street extract does not cover every suburb.

## Keep it small

Routine refresh must run without LLM calls. Agents discover sources and fix exceptions; they should not browse every listing on every run. Validate changes with focused offline tests, a small live adapter sample when needed, and an installed-app check. Do not refresh the whole city merely to test software.

Defer hosting, accounts, shared-car coordination, live navigation, tours, social/crime scoring, and always-on scheduling. Users can schedule `housing refresh` themselves. Profile R5 before considering a Rust rewrite: Python currently coordinates a Java routing engine.

[Competitor and backend research](FEATURE-RESEARCH.md) records the evidence behind these choices.
