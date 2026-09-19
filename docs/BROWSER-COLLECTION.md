# Browser-assisted collection

Browser collection fills declared gaps that the bounded HTTP adapters cannot parse. It is a private, operator-run workflow: the CLI emits a read-only DOM function, a browser evaluates it on an already rendered results page, and the CLI validates and imports the saved JSON. It does not start an agent or browser, log in, bypass a challenge, or establish citywide coverage.

## Collect a source

Use the same private workspace throughout. Put `--workspace PATH` before the subcommand when it is not `.housing`.

1. Save the user's city and search requirements with `housing setup`, then inspect the gap plan:

   ```sh
   housing assisted plan
   ```

   Resume entries come first, followed by untouched assisted portals. The plan merges the city catalog, configured custom sources, recent HTTP outcomes, and prior browser captures. It opens nothing and makes no network request.

2. Open the selected source's public search page in a browser. Apply the requested filters through the site's UI and verify the visible controls and result summary. The saved Room & Route criteria are context only; they are not automatically applied to the website.

3. Save the filters actually verified on the website in a private options file. For example, save this as `.housing/browser-options.json`:

   ```json
   {"criteria":{"max_rent":3200,"min_bedrooms":2}}
   ```

   Then print the extractor for that source and the original filtered search URL:

   ```sh
   housing assisted script --source domu-assisted --recipe domu \
     --search-url 'https://www.domu.com/chicago-il/apartments?...' \
     --options .housing/browser-options.json
   ```

   Recipes are `domu`, `compass`, `apartments`, `zillow`, `apartmentlist`, `rentcafe`, and `generic`. Catalog sources may provide tested recipe options; keys in `--options` override those defaults and also record the criteria actually applied. The output is a self-contained pure DOM function for evaluation in the rendered page. It reads all result cards in one batch. It does not click, navigate, or depend on a particular browser automation SDK.

4. Evaluate the printed function on the page and save the returned object as local JSON, for example `capture.json`. Keep captures under `.housing/` or another private ignored location; raw portal evidence does not belong in Git. Keep the same original `search_url` for every page in one traversal; `pages_visited` records the exact current page and `next_url` records the next page.

   Pass the filters actually checked through the `--options` JSON file, as shown above. If the page is unfiltered, save `{"criteria":{"scope":"unfiltered"}}`; for a partial match, describe only the visible applied subset. The script defaults to empty criteria and never treats saved workspace criteria as applied website filters. For Zillow, set `"page_verified": true` only after scrolling through the rendered results and confirming the final card; otherwise the extractor deliberately keeps the current page as the resume point.

5. Import and resume:

   ```sh
   housing assisted import capture.json
   housing assisted plan
   ```

   Navigate to the reported resume URL, evaluate a fresh script on that page using the same original `search_url` and criteria, save a new capture, and import it. A blocked or failed page can be imported with no listings and a valid `next_url`; existing inventory and resume progress remain intact.

6. Leave captures `partial` while a next page, enabled next control, result cap, or uninspected card set remains. Use `complete` only when the explicitly traversed page scope has no next page and every card on the final page was considered. This means the searched pages are complete, never that the source or city is complete.

## Capture contract

```json
{
  "source": {"id": "domu-assisted"},
  "search_url": "https://www.domu.com/chicago/apartments-for-rent?...",
  "observed_at": "2026-09-19T18:00:00Z",
  "status": "partial",
  "pages_visited": ["https://www.domu.com/chicago/apartments-for-rent?..."],
  "next_url": "https://www.domu.com/chicago/apartments-for-rent?page=2",
  "evidence_note": "Rendered public cards; filters visibly checked; next page present.",
  "criteria": {"max_rent": 3200, "min_bedrooms": 2},
  "listings": [
    {
      "source_id": "stable-provider-id",
      "url": "https://www.domu.com/chicago/listing/example",
      "title": "Example listing",
      "address": "100 Example Street, Chicago, IL",
      "unit": null,
      "grain": "property",
      "rent": null,
      "bedrooms": 2,
      "bathrooms": null,
      "sqft": null,
      "notes": "Advertised starting rent was a range, not an exact unit rent."
    }
  ]
}
```

`status` is `partial`, `complete`, `blocked`, or `error`. Blocked and error captures contain no listings. All timestamps need a timezone. Source, search, page, next, and listing URLs must use the declared source origin. Source IDs must be stable across captures. Unknown facts remain `null`.

Property cards often show a rent range or “starting at” price. Do not turn either into an exact unit rent. Keep the property or floorplan grain and `rent: null`; for promising properties, inspect the public detail page and capture exact available-unit rows only when the page provides stable unit identities and exact facts.

## Generic and new-city sources

For another city, add the public source to the private workspace configuration first with a stable `id`, `adapter: "assisted"`, absolute `url`, and a permission note. Inspect the rendered DOM before using `generic`, then put its selectors and applied criteria together in the options file, for example `{"cards":".listing","link":"a.details","criteria":{"scope":"unfiltered"}}`. A capture from an undeclared custom source is rejected.

Stop and record `blocked` when login, CAPTCHA, human verification, or another access control appears. Ask the user for a handoff only when the browser actually requires their action. Do not make a blanket privacy handoff before ordinary public pages have been checked.

Finish with `housing assisted plan` and `housing status --json`. Report imported observations, visited pages, remaining resume points, unknown facts, and source-specific failures. Verified browser recipes demonstrate accessible public cards within bounded pages; they remain partial observations, not city coverage.
