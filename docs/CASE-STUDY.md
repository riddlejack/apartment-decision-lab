# From a Chicago search to a reusable tool

The original July 2026 project assembled 32,242 captured listing occurrences into 16,581 canonical listing records. These are different grains: repeated captures are not new apartments, and canonical records are not proof of current availability. The final interface grouped 10,913 address/unit records across its main and long-tail datasets.

Collection combined shared HTTP parsers, structured website responses, scripted browser extraction, saved page imports, and targeted manual verification. It was not a single autonomous scraper. Several browser captures retained executable extraction loops, but parts of the integration depended on parsing tool transcripts and snapshot-specific IDs.

An offline reconstruction replayed the retained AppFolio/ManageBuilding parser functions against 19 initial saved captures: 882 cards, matching the original provider-ID sets. Sixteen captures were nonempty; three returned zero. That establishes reproducibility against those inputs, not permission, current availability, or present-day site compatibility.

The earlier commute system used OpenStreetMap, official transit schedules and R5 to model walking, biking and walking plus transit. It precomputed 672 weekly departure slots for 7,013 origins and fixed private destinations. Its 24 GB Java heap setting and whole-week preprocessing were substantial costs for someone who just wanted to compare a few homes.

This release extracts the repeatable parts: shared parsers, source-scoped observations, explicit unknowns, private household configuration, bounded route requests, caching, and deterministic comparison. Users choose destinations, permitted modes and requested travel windows. Automatic HTTP collection and local routing do not spend LLM tokens. Browser-assisted collection still needs an agent or person. No measured speedup against the old research process is claimed.

## What changed for us

I was searching with three roommates. The early options we were considering were cramped and around $2,000 per person per month. We ended up with a much larger apartment, four bathrooms, and rent of about $1,230 per person, with a commute I was happy with. That is roughly $770 less per person each month than those earlier options.

Those housing and rent outcomes are my report, with the per-person basis confirmed on September 19, 2026. The earlier price was an option under consideration, not rent we had already been paying. This is an account of one search, not a controlled estimate of savings or a benchmark against Apartments.com. Our home address and work destinations are not published.

## What the headline numbers mean

The README graphic uses these aggregate facts, rechecked against the retained files on September 19, 2026:

| Number | Basis |
| --- | --- |
| 32,242 listing captures | Counted rows in the raw occurrence export. Repeat searches and syndicated listings are included. |
| 16,581 consolidated records | Counted rows in the closeout canonical export. Unresolved identities remain, so these are not proven unique physical apartments. |
| 2,930 candidate-screen records | Counted rows in the historical broad candidate export: advertised 4+ bedrooms, 2+ full bathrooms, rent at or below $7,500, and selected rejection/ambiguity classifications excluded. This was a wide review pool, not a tour-ready shortlist. |
| 7,013 commute locations | Origin count in the original route manifest; route availability varied by mode. |
| 672 weekly departure slots | A representative week at 15-minute intervals. Equivalent service days were reused; these are not 672 independent engine runs or observed commutes. |

The broad candidate screen predates the reusable package. Its handling of missing fields is not the current filtering policy, which retains unknowns for review. The routing manifest is a later stage of the original search; its 7,013 origins are not a subset of the 2,930 candidate-screen records.

[Aggregate data and evidence hashes](assets/chicago-search-stats.json) preserve the basis without publishing the underlying private files. The visual describes the original July search, not a fresh run of today's package. The September browser-collection check is documented separately in [current scope](NEXT-STEPS.md).

## Public-data boundary

The original raw archives, workplace destinations, destination-specific commute matrices, messages and private household notes remain outside this repository. Historical listing pages and photos have not been cleared for wholesale redistribution. The downloadable examples here are invented and marked synthetic. The CLI can export a user's own imported or collected facts, subject to their source terms.

Five original website commits were made on July 18, 2026. They are retained in the private original workspace. The public repository starts with a new baseline because the old history embeds private configuration. No dates or authorship were fabricated to populate a contribution graph.

## What remains to prove

This repository does not reproduce exhaustive Chicago coverage, guarantee a listing is available, or validate every city's feeds. Current source access, model accuracy at a particular departure time, and a second city's integration are separate checks. Automated test results and a bounded routing proof should be read at their stated scope, not as validation of the entire housing market.
