# Listing collection

The collector supports an owner-authorized JSON feed plus server-rendered listing cards from two property-management platforms: `json`, `appfolio`, and `managebuilding`. It is deliberately small. It does not use credentials, submit forms, call private APIs, render JavaScript, fetch listing details, evade blocks, or follow pagination.

## Configure a source

Sources are city-independent. Add an authorized feed or listings URL to `.housing/config.json`; do not add source URLs to the package itself. Sources should remain disabled until authorization and terms have been checked.

```json
{
  "id": "example-owner-feed",
  "adapter": "json",
  "url": "https://housing.example.org/authorized/listings.json",
  "enabled": false,
  "permission_note": "Feed owner Example Housing Cooperative authorized automated retrieval of this exact endpoint on 2026-09-18."
}
```

`enabled` must be exactly `true`, and `permission_note` must explain why collection is permitted. A note is an operator record, not a substitute for checking the platform's and property manager's current terms. `robots.txt` is a technical access rule, not permission by itself. If permission is unclear, leave the source disabled and import user-provided CSV or JSON instead.

As checked on 2026-09-18, AppFolio's [Property Manager Websites Terms of Service](https://www.appfolio.com/terms/listings) prohibit automated retrieval, scraping, or indexing, even though at least one public listings host returned an allowing robots policy. Do not enable an AppFolio source without separate authorization that resolves that conflict. Buildium's [Resident and Applicant Center Terms](https://www.buildium.com/resident-center-terms-of-service-2/) also restrict non-permitted use and allow property managers to impose additional requirements; a ManageBuilding source likewise needs source-specific permission. These terms can change, so review them again when configuring a source.

The `json` adapter is the clean path for a property manager or feed owner who has authorized access. The response may be a JSON array or `{ "listings": [...] }`. Each listing follows the application's listing schema and needs a stable `source_id` (or `id`). The collector overwrites `source` with the configured source ID and stamps one collection time so identities and observations stay source-scoped. Supported input fields are:

```json
{
  "source_id": "unit-101",
  "url": "/rentals/unit-101",
  "title": "Example apartment",
  "address": "101 Example Avenue",
  "unit": "2A",
  "grain": "unit",
  "rent": 1450,
  "total_monthly_cost": 1505,
  "bedrooms": 1,
  "bathrooms": 1,
  "lat": null,
  "lon": null,
  "historical": false,
  "notes": "Owner-supplied synthetic example"
}
```

Strings masquerading as numbers, duplicate source IDs, invalid grain, non-HTTP listing URLs, invalid coordinates, and malformed records are rejected. An empty array is explicit empty-state evidence. If an object reports `next`, `next_url`, or `has_more: true`, collection succeeds as a partial first page and does not follow it.

## Runtime boundary

`collect_source(source, timeout=20)` makes at most two requests:

1. one same-host `robots.txt` request;
2. one listings-page request, only when robots permits it (a standard `404` or `410` means no robots policy was published).

The runner uses a descriptive user agent, a 5 MiB response limit, no retries, and does not follow HTTP redirects. It treats HTTP `401`, `403`, and `429`, challenge pages, human-verification pages, and cross-host redirects as `blocked` and does not try another route. Other redirect responses are errors that should be fixed by configuring the final URL. If robots cannot be checked because of an error or nonstandard failure response, collection stops rather than assuming permission. Each call reports its HTTP attempt count in `requests`.

The response status is one of:

- `success`: at least one recognized card or JSON record was parsed;
- `empty`: a recognized source page explicitly says that no rentals are available;
- `blocked`: robots, the HTTP response, or a challenge page prevents ordinary public access;
- `error`: invalid configuration, network/HTTP failure, an oversized or unexpected response, parser failure, or content with neither known records nor explicit empty-state evidence.

Pagination is detected but never followed. A successful first-page result sets `partial: true` and says that pagination is unhandled. A page with unfamiliar markup is an error, not an empty or successful run.

## Evidence and grain

`parse(adapter, html, base_url, source_id, observed_at=None)` performs no network or database work. Each result receives a stable ID of `<configured source id>:<provider listing id>`, and its canonical detail URL has query parameters and fragments removed.

Every parsed row also records `parser_version` and `source_content_sha256`. The hash covers the exact input bytes (UTF-8 for a direct string input), so a stored observation can be tied to one source response without retaining or publishing the raw page/feed.

Fields come only from the same listing card or JSON record:

- `rent` means gross **base monthly rent**. AppFolio `RENT` populates it. `TOTAL MONTHLY PRICE` may include mandatory fees, so it is retained separately as optional `total_monthly_cost` and never substituted for rent. If only the total is present, `rent` stays `null`.
- ManageBuilding records are `unit` grain when its title explicitly separates a unit with ` - `. A title without that marker is `property` grain only when the provider labels it `SingleFamily`; otherwise its grain is `unknown`.
- JSON records retain distinct numeric `rent` and optional `total_monthly_cost` fields supplied by the authorized feed owner.
- Studio is numeric `0` bedrooms. Unknown rent, bedrooms, bathrooms, unit, and coordinates stay `null`.
- A price range is not converted into a single rent. `$0`, “call for rent,” deposits, and text without one positive monthly amount become `null`.
- Availability is retained in `notes`; it is not interpreted as a historical flag. Newly collected cards use `historical: false`.

This keeps a card's rent and bedroom count together and avoids combining a floorplan-wide price with a unit-level bedroom count. The core application owns run history and database writes.

## Known limits and cost

Collection costs one robots request plus one feed/listings-page request per enabled source per run. There are no detail requests. AppFolio and ManageBuilding can change their HTML at any time; an unrecognized page must be reviewed before changing the parser. JavaScript-only pages, login-protected inventory, and sources that disallow collection are unavailable to this runner. First-page collection is incomplete when the source paginates.

The tests use invented synthetic HTML. Historical raw listing pages may be useful for local parser validation, but they are neither bundled nor published because they contain old listing data and source-specific context.

### Current evidence (2026-09-18)

No useful live market source currently has verified permission. A bounded AppFolio probe made two requests (robots plus one listings page), found 16 unique listing cards, and followed no pagination or detail links. The platform's official terms review above means that result is **unavailable for use**, despite the allowing robots response. No raw page or listing payload from the probe is retained in this project.

The working end-to-end proof is instead an honestly synthetic, user-controlled local JSON feed: its local server publishes an allowing robots rule and one invented listing, and the collector completes with exactly two requests. Local, unpublished historical-fixture checks parsed 33/33 unique AppFolio cards and 69/69 unique ManageBuilding cards, with both base rent and bedrooms present on every tested card. Those checks verify adapter compatibility with retained HTML shapes, not current permission or market completeness.
