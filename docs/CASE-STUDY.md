# From a Chicago search to a reusable tool

The original July 2026 project assembled 32,242 captured listing occurrences into 16,581 canonical listing records. These are different grains: repeated captures are not new apartments, and canonical records are not proof of current availability. The final interface grouped 10,913 address/unit records across its main and long-tail datasets.

Collection combined shared HTTP parsers, structured website responses, scripted browser extraction, saved page imports, and targeted manual verification. It was not a single autonomous scraper. Several browser captures retained executable extraction loops, but parts of the integration depended on parsing tool transcripts and snapshot-specific IDs.

An offline reconstruction replayed the retained AppFolio/ManageBuilding parser functions against 19 initial saved captures: 882 cards, matching the original provider-ID sets. Sixteen captures were nonempty; three returned zero. That establishes reproducibility against those inputs, not permission, current availability, or present-day site compatibility.

The earlier commute system used OpenStreetMap, official transit schedules and R5 to model walking, biking and walking plus transit. It precomputed 672 weekly departure slots for 7,013 origins and fixed private destinations. Its 24 GB Java heap setting and whole-week preprocessing were substantial costs for someone who just wanted to compare a few homes.

This release extracts the repeatable parts: shared parsers, source-scoped observations, explicit unknowns, private household configuration, bounded route requests, caching, and deterministic comparison. Users choose destinations, permitted modes and requested travel windows. Routine operations do not spend LLM tokens. That is an architectural property, not a measured speedup against the old research process.

## Public-data boundary

The original raw archives, workplace destinations, destination-specific commute matrices, messages and private household notes remain outside this repository. Historical listing pages and photos have not been cleared for wholesale redistribution. The downloadable examples here are invented and marked synthetic. The CLI can export a user's own imported or collected facts, subject to their source terms.

Five original website commits were made on July 18, 2026. They are retained in the private original workspace. The public repository starts with a new baseline because the old history embeds private configuration. No dates or authorship were fabricated to populate a contribution graph.

## What remains to prove

This repository does not reproduce exhaustive Chicago coverage, guarantee a listing is available, or validate every city's feeds. Current source access, model accuracy at a particular departure time, and a second city's integration are separate checks. Automated test results and a bounded routing proof should be read at their stated scope, not as validation of the entire housing market.
