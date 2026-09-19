# Features to borrow, work to avoid

September 19, 2026. Research snapshot made before v0.2 implementation. “Our current state” below refers to v0.1; see [current scope](NEXT-STEPS.md) for what subsequently shipped. Review of publicly documented features, not a live execution or latency benchmark. The scope is rental discovery and the adjacent renter workflow; private backend details and every mobile UI variation cannot be established from documentation.

## Apartments.com

Apartment search is free for renters. Applications/screening and other transaction services are separate. Being free alone is not this project's advantage. [Renter help](https://renterhelp.apartments.com/article/559-how-can-i-search-for-an-apartment)

| Documented capability | Our current state | Useful free implementation |
|---|---|---|
| Map/list search, multiple search areas, commute-time boundaries | Comparison list; no map | Open map renderer, listing markers, selected areas, network-based commute overlays. Map tiles/geocoding still need a suitable provider or local data. |
| Rent, property type, beds/baths, amenities, lease length and move-in filters | Rent, beds/baths, source, text | Extend the schema and intake; retain unknown fields for follow-up. |
| Small buildings, duplexes, new construction, owner listings, rooms, specials, short-term and some city-specific filters | Not implemented | Add only fields sources actually provide; apartment versus room distinctions prevent misleading prices. |
| Favorites, saved searches, new-match emails and side-by-side comparison | Household comparison; no persistent shortlist/saved filter sets or alerts | Local saved criteria, shortlist/reject/notes, comparison cards and optional notifications. |
| Unit availability, floor plans, photos, site maps and unit amenities | Unit/floorplan/property distinction only | Preserve unit-level facts and link to original media/tours. A building's cheapest floorplan is not necessarily the matching unit. |
| Monthly and one-time expense calculator, lease/date options, parking/pet/storage charges | Base rent and optional total monthly price stored | Transparent budget calculator and per-roommate allocation, with unknown fees shown explicitly. |
| 3D tours, interior measurement and exterior tours | None | Link existing source tours; producing new tours is not a software-only replacement. |
| Neighborhood guides, schools/POIs, renter reviews, market information | None | Defer. Optional public POI layers later; do not manufacture reviews or imply copied proprietary scores are free data. |
| Typed/voice AI search, listing questions and AI-assisted tours | External agents can operate CLI | Intake forms and saved config first; optional agent translation into validated filters, not an LLM on every refresh. |
| Tour booking, messaging, applications/screening, leases, payments, insurance | None | Link back to the listing/contact workflow; rebuilding a transaction marketplace is outside scope. |

Sources: [search tools](https://www.apartments.com/blog/the-most-important-aspects-of-your-apartment-search), [expanded filters](https://www.apartments.com/grow/learning-center/new-rental-search-filters), [favorites and notifications](https://renterhelp.apartments.com/article/250-how-do-i-keep-track-of-listings-that-interest-me), [unit details](https://www.apartments.com/blog/how-apartments.com-helps-you-find-the-perfect-fit), [cost calculator](https://renterhelp.apartments.com/article/1176-how-do-i-estimate-rental-costs-for-a-specific-unit), [renter services](https://www.apartments.com/renters/). Features and data vary by listing.

Priority additions: reusable collection, square footage and essential amenity/availability filters, a map, saved criteria/shortlist, clear total costs, and visible changes since refresh. Existing household-specific mode restrictions, weekly commute comparison and exports remain useful complementary capabilities.

## Other collection tools

**HomeHarvest:** MIT Python package for Realtor.com. Supports rentals and other listing types; city/ZIP/address/radius searches; beds/baths/price/size/lot/year filters; listing/update date windows; sorting; limits, offsets and sequential/parallel pages; CSV/Excel and structured Python results. Its schema includes identifiers, coordinates, descriptions, fees, units, media links, pets, parking and contact fields. Extra detail enrichment increases requests. No documented turnkey multi-source monitoring or household ranking. Candidate adapter, not the whole collection system. Current source compatibility and field completeness are untested here. [Repository](https://github.com/ZacharyHampton/HomeHarvest)

**Flathunter:** AGPL rental monitor with configurable search URLs, price/size/room/title filters, price-per-area caps, persistent seen-listing IDs, polling, optional heartbeat, configurable messages and Telegram/Mattermost/Slack/Apprise notifications. CLI, web interface, Docker and deployment configurations are supplied. Its commute integration uses Google's paid Distance Matrix service. Current supported portals are European; some integrations have browser or paid anti-bot-service dependencies. Borrow the runner/configuration/notification pattern, after license review for code reuse; do not assume free code means every source works free or unattended. [Repository](https://github.com/flathunters/flathunter), [configuration](https://github.com/flathunters/flathunter/blob/main/config.yaml.dist)

**HousingFeed:** commercial normalized feed with geography/source/rent/bedroom/availability/freshness filters, map bounds, sorting, row caps, new-listing queries, optional slower live portal refresh and JSON/CSV/XLSX/XML output. Records distinguish units/floorplans, rent/size ranges, source IDs, URLs, media, amenities and collection timestamps. Useful ideas: explicit freshness, nullable fields and stable source identity. A new-listing query is not a complete price-change/removal feed; disappearance from a partial query must not retire an apartment. Its docs distinguish weekly sources from older portal snapshots, and internal-use data from separately licensed public display. API convenience does not establish current Chicago coverage. [Documentation](https://housingfeed.com/docs)

## Commute speed: confirmed versus inferred

TravelTime's own CoStar case study identifies Apartments.com as a customer and describes commute filtering, rush-hour/no-traffic choices and isochrone maps. It describes a fixed annual unlimited-request license for this class of integration. This supports a specialized routing service behind the UI; it does not reveal Apartments.com's server count, cache keys, route precomputation or measured response latency. [Provider case study](https://traveltime.com/case-study/costar-property-portals)

An isochrone represents locations reachable within a travel-time limit through the transport network. It is not a distance circle. Fast reachable-area search and full per-person, round-trip, multi-day ranking are different workloads.

TravelTime documents a fast JSON matrix supporting up to 100,000 locations and many-to-one searches. Its Protobuf service targets high-volume consumer search; its FAQ claims 100,000 travel times in under 150 ms. This is a vendor performance claim, not measured Apartments.com latency. The fast variants use a weekday-morning scenario with limited controls; configurable date/time/transport options belong to the regular endpoint. The comparison lists the Protobuf variant as one-to-many, so do not transfer its timing claim to every reverse-search workload. [Endpoint comparison](https://docs.traveltime.com/api/reference/travel-time-distance-matrix-comparison), [performance FAQ](https://docs.traveltime.com/api/overview/faqs)

R5 already targets bulk multimodal travel-time analysis. Test our use of it before replacing it with a second engine. [R5 project](https://github.com/conveyal/r5)

Engineering proposals, not claims about Apartments.com's internals:

- Reuse prepared street/transit graphs; distinguish cold graph building, warm calculation and cached results when measuring performance.
- Batch origin/destination work instead of making one external request per listing.
- Reuse times across units with the same valid entrance/location; do not merge unit facts or assume every building entrance is equivalent.
- Cache per origin/destination/mode/time/network combination. Our current fingerprint covers the whole selected origin set, so an added apartment can invalidate a whole batch. Finer cache entries could compute only new/changed origins.
- Filter known factual mismatches first; unknown essential fields remain pending. Keep route-time suitability separate from geographic distance.
- A travel-time surface or many-to-one query may accelerate a common workplace search. Direction, arrival/departure semantics and time-dependent transit must remain correct; simply reversing an outbound schedule is invalid.
- Use map contours for explanation. Simplified polygons must not silently exclude apartments near a boundary; validate suitability with route results.
- Keep CPU/memory caps. Consider a persistent local routing worker only if profiling shows engine startup is a material cost. No new always-on service is required by default.

No speedup is claimed until measured on fixed origins, destinations, feeds, time windows and hardware. Do not conflate a one-scenario website preview with the old exhaustive weekly matrix.

## Validation without a citywide refresh

1. Use retained captures and synthetic cases for parser/schema/deduplication work. Cover missing values, units sharing an address, conflicting prices, pagination termination, changed records, interrupted runs and failures. Never publish private original fixtures.
2. Validate each chosen adapter with a small current source sample. For shared adapters, check different host/page shapes. Independently inspect returned facts and explicitly exercise pagination. Scale up only when the sample reveals a reason.
3. Run collection twice to verify repeatability and changed-record handling; controlled fixtures establish changes that a short live interval may not contain. An empty/error page must not erase inventory.
4. Benchmark routing on a small fixed coordinate set: cold setup, warm computation, cache hit and one-added-origin behavior. No fresh listing scrape is needed for this.
5. Broader collection becomes appropriate when proving claimed Chicago coverage, not as a prerequisite to every software change. A bounded sample cannot justify a citywide completeness claim.

## Distribution and operating cost

Ship a frozen example/demo and on-demand tools. Do not keep a public demo's listings current. The user's desired product is a reusable repository, not a subscription to maintaining a live Chicago search.

A standalone scheduled script can collect, normalize, diff and notify without any model calls. This is different from waking Codex to supervise every run. Network, compute and optional provider fees still exist. An agent is for setup, discovery or selected repairs; no automatic agent invocation on failures by default. Scripted browser extraction is also distinct from an LLM reading and clicking every page.

Stop after a useful installer-to-refresh proof. No recurring automation, provider purchase, usage reset or full Chicago crawl was initiated for this research.
