---
name: collect-browser
description: Collect apartment result cards from declared public browser sources into Goldblum's private assisted ledger.
---

Read `docs/BROWSER-COLLECTION.md`, then run `goldblum assisted plan` in the user's private workspace. Resume saved pagination first; otherwise choose an untouched assisted source that can add useful coverage.

Open the declared public search page and apply the user's filters through the site UI. Verify the visible filters. Saved config criteria are not automatically applied: record only visibly checked filters, or use `{"scope":"unfiltered"}`.

Run `goldblum assisted script --source ID --recipe domu|compass|apartments|zillow|apartmentlist|rentcafe|generic --search-url ORIGINAL_URL --options OPTIONS.json`. The options path is a private JSON file; put only visibly applied criteria in it, or use `{"criteria":{"scope":"unfiltered"}}`. Evaluate the emitted pure DOM function on the rendered page and save the returned object as local JSON. Extract cards in one DOM batch, not one model call per card. For a new generic source without catalog options, inspect the DOM first and include its selectors in the file.

Keep the original filtered `search_url` and criteria across pages; record the exact current URL in `pages_visited`. Import with `goldblum assisted import capture.json`, rerun the plan, and continue from `next_url`.

Leave status `partial` while pagination, caps, or uninspected cards remain. `complete` covers only explicitly searched pages. Never claim source or city completeness.

Keep unknowns null. A range or “starting at” price is not exact unit rent. Preserve property/floorplan grain, then inspect promising public detail pages for stable available-unit rows before a decision.

Do not log in or bypass CAPTCHA, verification, or access controls. Record a status-only blocked/error capture and request user handoff only when an actual browser action requires it. Existing inventory must survive all failures.
