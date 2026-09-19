---
name: setup-search
description: Set up a private apartment search using the installed housing CLI.
---

Run `housing doctor`, then `housing setup --city Chicago --residents 3 --budget-per-person 1200 --bedrooms 3 --bathrooms 2` with the user's actual requirements. Residents and bedrooms are separate choices. Inspect `housing sources check`, run `housing collect`, and open `housing review`. Unknown listing details stay in the review queue; do not discard them or invent facts.

Read docs/COLLECTION.md for adapters and adding another city's sources. Use the catalog to report coverage gaps and target useful new sources; do not repeat a full browser crawl. Read docs/ROUTING.md only if commutes are needed. Enter destinations and travel modes in the UI; Chicago network inputs can be downloaded with `housing network --download`. Set the timezone and a valid transit date. Commute time, not a radius around work, determines suitability.

Keep household coordinates out of Git. `--workspace PATH` goes before the subcommand; custom workspace directories need their own Git exclusion. Use `uv run housing` in a checkout. Report successful sources, unresolved gaps and any additional setup; never claim every apartment is covered.
