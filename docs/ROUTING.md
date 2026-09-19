# Local routing

Goldblum routes locally with [R5 through r5r](https://ipeagit.github.io/r5r/). The Python package handles configuration, bounded work, caching, unavailable values, and household ranking. The bundled R runner supplies the actual OSM street paths and GTFS schedule calculations. There is no straight-line transit fallback and no LLM dependency.

Routing is optional. Viewing, importing, and ranking saved results do not require R or Java. Computing new routes requires:

- R, Java, and the R packages `r5r` and `data.table`;
- a routing directory containing an `.osm.pbf` street extract and one or more GTFS `.zip` feeds, or a compatible `network.dat` previously built by r5r;
- a requested date inside every GTFS archive's declared calendar coverage.

## Fresh setup

The [official r5r introduction](https://ipeagit.github.io/r5r/articles/r5r.html) documents the engine setup and currently requires JDK 21. On macOS with Homebrew, a short installation is:

```sh
brew install r openjdk@21
Rscript -e 'install.packages(c("r5r", "data.table"), repos="https://cloud.r-project.org")'
goldblum doctor
```

For Chicago, preview the public downloads, then fetch the street extract and CTA, Metra and Pace schedules:

```sh
goldblum network
goldblum network --download --city Chicago
```

This configures the network directory and reuses files already downloaded. `--download --refresh` replaces inputs and removes the derived graph so the next route run rebuilds it. The Chicago street extract is city-sized: for suburban commutes, use a larger OSM extract covering **both homes and destinations**. Transit feeds alone do not extend the street network. Pace publishes its feed for noncommercial use; all agency terms remain applicable.

For another city, place its `.osm.pbf` street extract and agency GTFS ZIP files together without unpacking them, then set `routing.network_dir` and the local IANA `timezone`. Set a date covered by all feeds. Automatic download setup currently supports Chicago only.

In the private workspace's `config.json`, set `timezone`, `routing.network_dir`, a `routing.date` inside every feed's service calendar, outbound/return times, resource limits, and each person's coordinates, destinations, and allowed modes. Then run:

```sh
goldblum --workspace my-search route
goldblum --workspace my-search compare
```

The first route command builds `network.dat` from the PBF and GTFS feeds. A fresh regional graph can take substantially longer and use substantially more memory than either small verification run described below. Start with a shortlist through `listing_ids`, a small transit window, one or two threads, and a realistic JVM cap; expand only after that bounded run succeeds. Later calls reuse the graph and request cache when their physical inputs still match. Origins with identical coordinates share matrix work while retaining separate listing records. Adding a listing at a new location computes only that location when the destinations, scenarios and network are unchanged.

## Configuration

`config.json` keeps the timezone at the top level and engine controls under `routing`:

```json
{
  "timezone": "America/Chicago",
  "people": [
    {
      "id": "resident-a",
      "name": "Resident A",
      "modes": ["walk", "transit", "bike"],
      "max_minutes": 45,
      "destinations": [
        {
          "id": "civic-site",
          "name": "Public civic site",
          "lat": 41.0,
          "lon": -87.0,
          "days_per_week": 3
        }
      ]
    }
  ],
  "routing": {
    "engine": "r5r",
    "network_dir": "/absolute/path/to/osm-and-gtfs",
    "date": "2026-07-21",
    "outbound_time": "08:00",
    "return_time": "17:30",
    "time_window_minutes": 10,
    "percentile": 50,
    "threads": 2,
    "max_memory_gb": 8,
    "max_trip_minutes": 120,
    "max_walk_minutes": 30,
    "walk_speed_kmh": 4.8,
    "bike_speed_kmh": 16,
    "max_lts": 2,
    "drive_enabled": false,
    "drive_parking_minutes": 0,
    "max_origins": 1000,
    "cache": true
  }
}
```

`date`, `outbound_time`, and `return_time` may also be set on an individual destination. The destination values override the routing defaults. Times use local 24-hour `HH:MM` notation in the configured timezone.

The main controls are:

| Key | Meaning |
| --- | --- |
| `network_dir` | Local directory containing public OSM/GTFS inputs and the R5 cache. |
| `date` | Schedule date. Transit computation stops before routing if this falls outside a GTFS archive's calendar coverage. |
| `outbound_time`, `return_time` | Independently routed departure times. Return is destination to home, not a copied outbound value. |
| `time_window_minutes` | Number of departure minutes sampled for transit. Direct modes use one deterministic departure because their R5 times do not vary by clock time. |
| `percentile` | Travel-time percentile returned from the transit window, normally `50`. |
| `threads`, `max_memory_gb` | Explicit CPU and JVM memory limits. One R process builds or loads the network and runs all requested matrices. |
| `max_trip_minutes` | Hard maximum for any route, including direct walking. |
| `max_walk_minutes` | Walking limit for transit access, egress, and transfers. It does not truncate the direct `walk` option. |
| `max_lts` | R5 bicycle level-of-traffic-stress ceiling, 1 through 4. |
| `drive_enabled` | Required global consent for direct driving. A person must also list `drive` in `modes`. |
| `drive_parking_minutes` | Fixed minutes added to each driving leg for parking and terminal overhead. |
| `listing_ids` | Optional list of shortlisted listing IDs. Only these origins are routed. |
| `max_origins` | Safety limit, default `1000`. A larger unfiltered request fails with instructions to select a shortlist or deliberately raise the limit. |

`rscript`, `java_home`, and `timeout_seconds` are optional advanced overrides. The Java locator recognizes standard macOS Homebrew layouts, including the JDK home nested below the Homebrew prefix.

## Mode behavior

Each person gets only the modes listed in that person's `modes` array.

- `walk` uses the OSM street network.
- `transit` asks R5 for its walking plus scheduled-transit option, including walking access and egress. R5 may choose a walk-only path when that is faster, so the payload labels this `r5_walk_transit` rather than claiming a transit vehicle was boarded.
- `bike` uses the OSM network and configured traffic-stress ceiling.
- `drive` uses R5/OSM free-flow road time plus the configured parking overhead on each leg. It has no live or historical congestion model.

Driving is disabled unless `drive_enabled` is true. It is always labeled `free_flow_osm_plus_parking`. Park-and-ride is not implemented and is never claimed.

The returned result for each allowed mode keeps `outbound_minutes` and `return_minutes` separately. A missing route is `null`, with a reason such as `outbound_route_not_found`; it is never converted to zero.

## Ranking

`rank_listings(listings, people, route_payload)` applies current household preferences to saved physical routes:

1. A direct bike or personal-car choice must use that same mode in both directions. This prevents choosing a car outbound when the return car would not be at the destination.
2. Walking and transit have no vehicle-custody constraint, so the fastest valid outbound and return legs may differ, such as `walk/transit`.
3. If `max_minutes` is set, the ranker first chooses among mode pairs whose two one-way legs each meet the cap. It uses a faster cap-breaching pair only when no cap-compliant pair exists, and marks `over_cap`.
4. For each destination, it chooses the lowest round-trip minutes under those rules.
5. `weekly_minutes` is the sum of each selected round trip multiplied by `days_per_week`.
6. `daily_minutes` is the weighted average round-trip time per active destination trip: `weekly_minutes / sum(days_per_week)`. It is not a calendar-day average.

A destination with `days_per_week: 0` is ignored for completeness, mode labels, and cap checks. If a positive-weight destination lacks a valid outbound/return combination, the person and listing remain incomplete. Listing output retains the per-person totals, mean weekly minutes, worst-person weekly minutes, cap breaches, and explicit missing-route records.

## Cache and provenance

Physical routes are cached under the caller's private routing output directory. The request fingerprint covers:

- selected listing IDs and coordinates;
- people, destination IDs and coordinates, allowed modes, dates, and times;
- engine parameters and adapter revision;
- OSM/GTFS source file names, sizes, and modification times.

`days_per_week` and `max_minutes` are preference inputs rather than route geometry. Editing either reuses the physical cache and refreshes derived route values and rankings. Changing a coordinate, mode, date, window, or network input invalidates the cache. `routes_match()` exposes the same check to the core application.

Each new payload also records SHA-256 digests for the OSM PBF and GTFS ZIP inputs, r5r/R/Java versions, feed publishers where available, declared feed date coverage, and active service counts for every requested date. Hashing occurs when a new engine payload is produced, not on each inexpensive state check.

If `network.dat` is older than an OSM or GTFS source in the same directory, computation stops and asks for a rebuild. This avoids silently querying a stale derived graph.

The derived `network.dat` and `network_settings.json` files are deliberately excluded from cache identity. A clean first run may create both files after its request fingerprint is calculated; excluding derived-file timestamps keeps that new payload current and lets the second identical request hit cache. A regression fixture covers this fresh-network sequence.

## Installed-engine orientation guard

During the September 18, 2026 live check, installed r5r 2.4.0 returned the direct-WALK return matrix with `from_id` and `to_id` reversed when routing from a one-row civic-destination table to an eight-row synthetic-home table. The requested direction was destination to home, while the raw rows were home to destination. Bike and walking-plus-transit jobs in the same process used the requested orientation.

The Python adapter checks each job against its exact requested origin-ID and destination-ID sets. It swaps columns only when more rows match the reverse orientation than the requested orientation. Correctly oriented jobs pass through unchanged. A regression test uses unequal table sizes and distinct ID namespaces to cover the observed WALK reversal alongside a correctly oriented transit job.

## Sanitized live verification

A bounded local proof used eight invented homes, two invented residents, and two public civic destinations unrelated to any prior household. It used a static date verified inside all three GTFS calendars, a three-minute transit window, one thread, and an 8 GB JVM cap.

R5/r5r completed the proof in about 24 seconds on the test machine while reusing an existing regional graph. That timing is not a fresh graph-build benchmark. It returned 40 allowed-mode rows: all 16 walking-plus-transit routes, all 8 bicycle routes, and 7 of 16 direct walks were complete round trips. The other 9 walks exceeded the configured 120-minute trip ceiling. All eight homes still had complete two-person rankings through allowed alternatives. The proof recorded four public-input SHA-256 hashes. A separate bounded check verified direct driving with explicit consent, free-flow labeling, and per-leg parking overhead.

An independent portability check used the small Porto Alegre public sample graph bundled with r5r, copied to a clean temporary network directory. With a 2019 date inside both bundled GTFS calendars, the `America/Sao_Paulo` timezone, one thread, a 2 GB JVM cap, and a three-minute window, the same `compute_routes()` entry point built the graph and returned complete walk, walking-plus-transit, bike, and explicitly enabled free-flow-drive round trips in about four seconds. Its second identical call hit cache. This verifies a fresh graph and different timezone; it does not establish coverage for arbitrary cities or current schedules.

Raw proof files, machine-local paths, and engine caches remain outside the repository under `/tmp`. The repository includes normalized route values for the explicitly synthetic demo homes and public civic destinations so the optional engine is not required to inspect the workflow. Those values are historical outputs from this model run; they are not observed commutes, current predictions, or evidence that any listing exists.
