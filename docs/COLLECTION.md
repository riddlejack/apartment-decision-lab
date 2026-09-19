# Fresh listing collection

Collection v0.2 provides a real, bounded path from a city catalog to normalized apartment records. Chicago ships with enabled public result surfaces for AppFolio, ManageBuilding/Buildium, ShowMojo, and Craigslist. The same runner also supports normalized JSON feeds and an optional HomeHarvest adapter. It makes no model calls.

This is declared-source coverage, not every apartment in Chicago. A successful source means its configured public result pages were parsed within the stated caps. It does not establish a citywide denominator, a platform-wide inventory total, or current terms permission.

## City catalogs

`housing.sources.source_catalog(city)` returns runnable, optional, and known assisted sources. `default_sources(city, search)` returns enabled runnable sources with the household search overlaid. Every catalog entry has `id`, `adapter`, `enabled`, `permission_note`, `catalog_source: true`, `max_pages`, `max_listings`, and `search`; direct HTTP entries also have `url`.

Chicago's disabled entries make known gaps visible: HomeHarvest/Realtor is optional; RentCafe, Domu, Entrata, Apartments.com, Zillow, Apartment List, and Compass need source-specific or user-assisted work. Baird & Warner's AppFolio host and SabbaticalHomes are disabled because current ordinary-request probes stop at a robots redirect and human-verification response respectively. No CAPTCHA, proxy, private API, login, or access-control bypass is attempted.

An unknown city returns a generic disabled catalog with optional HomeHarvest and source-discovery guidance. Its defaults are empty, so custom sources still work and the application does not pretend to provide national coverage.

## Configure a source

```json
{
  "id": "example-owner-feed",
  "adapter": "json",
  "url": "https://housing.example.org/listings.json",
  "enabled": true,
  "permission_note": "Public or owner-provided feed; scope reviewed by the operator.",
  "max_pages": 3,
  "max_listings": 500,
  "max_requests": 6,
  "search": {"max_rent": 3200, "min_bedrooms": 2, "min_sqft": 900}
}
```

`permission_note` is an operator record. `robots.txt` is checked as a technical access rule, but an allow rule does not determine terms or legal permission. HTTP `401`, `403`, and `429`, challenge pages, and cross-host redirects stop collection.

A normalized JSON response may be an array or `{ "listings": [...] }`. Records need a stable `source_id` or `id` and may provide `url`, `title`, `address`, `unit`, `grain`, `rent`, `total_monthly_cost`, `bedrooms`, `bathrooms`, `sqft`, `available_date`, `property_type`, `amenities`, `pets`, `parking`, `lat`, `lon`, `historical`, and `notes`.

Unknown facts remain `null`. Search filters reject only known mismatches, so an apartment with unknown square footage is retained for follow-up rather than silently discarded by `min_sqft`. The same rule applies to other missing facts. When `max_rent` is absent, `residents * budget_per_person` can provide the shared maximum.

## Pagination, retries, and partial results

`collect_source(source, timeout=20)` requests same-host `robots.txt`, then result pages. JSON recognizes `next`, `next_url`, `links.next`, `pagination.next`, and `has_more` with a page or cursor. HTML follows an explicit same-host next link. Defaults remain one page; hard limits are 10 pages, 5,000 listings, 20 requests, and 5 MiB per response.

One retry is allowed for connection errors and transient `408`/`5xx` responses, within `max_requests`. `resume_url` may restart an interrupted traversal and must stay on the configured host. Completed records survive a later page failure and return `status: partial`, `partial: true`, errors, and a resume URL when available. Reaching a page, listing, or request cap also sets `partial: true`. No failed or partial run retires stored inventory.

Every result contains `status`, `listings`, `requests`, `partial`, `message`, `errors`, and concise `coverage` counts for pages, records, duplicates, filtered known mismatches, and known/unknown key fields.

The optional HomeHarvest adapter invokes sequential rental search with `extra_property_data=false` and a listing limit. It intentionally omits provider-side square-foot filters to retain unknown square footage. HomeHarvest does not expose its underlying HTTP request count, so `requests` is `null` rather than guessed. In a checkout, install it with `uv sync --extra collect`. For a tool installation:

```sh
uv tool install --force --with homeharvest==0.8.18 git+https://github.com/riddlejack/apartment-decision-lab
```

Copy the `realtor-homeharvest` entry from `housing sources catalog` into your workspace's `config.json` sources and set `enabled` to `true`. Set `search.location` to the desired city, keep a small `max_listings` while checking it, and run `housing collect --source realtor-homeharvest`. The extra is optional; default sources do not require it.

## Evidence and grain

`parse(adapter, html, base_url, source_id, observed_at=None)` does no network or database work. It supports `appfolio`, `managebuilding`, `showmojo`, `craigslist`, `sabbaticalhomes`, and normalized `json`. Each row receives a source-scoped ID, canonical public detail URL, parser version, collection timestamp, and SHA-256 of its source page or record.

Facts stay at one result-card grain. Base rent is separate from AppFolio's total monthly price. A price range is not converted into a point rent. Studios are zero bedrooms. Unit, floorplan, property, and unknown grains remain distinct. Available date, square feet, property type, amenities, pets, and parking are populated only when the card or feed reports them.

## Bounded live validation on September 19, 2026

Ordinary public requests produced current normalized records from six enabled Chicago sources without detail-page crawls:

| Source | Adapter | Requests | Returned | Result |
|---|---|---:|---:|---|
| SPTREC | AppFolio | 2 | 9 | complete configured page |
| Landmark Realty Group | AppFolio | 2 | 32 | complete configured page |
| Six Zero Six Realty | AppFolio | 2 | 90 | complete configured page |
| Edge and Up | ManageBuilding | 2 | 1 | complete configured page |
| Domain Property Management | ShowMojo | 2 | 10 | complete configured page; 7 reported square feet |
| Forte Properties | ShowMojo | 2 | 12 | complete configured page; 2 reported square feet |

Craigslist Chicago returned 120 cards in two requests and is reported as partial because it reached the configured listing cap. All evidence above is count/status evidence; raw listing payloads are not bundled or published.
