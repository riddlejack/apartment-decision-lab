# Example data and attribution

`listings.json` contains eight invented homes, asking rents, and unit facts. `household.json` contains invented people and unrelated public civic destinations. These authored examples use the repository's MIT license.

`routes.json` contains genuine model outputs for those examples, computed on September 18, 2026 for a **July 21, 2026** schedule date. The underlying map/transit input snapshot was retrieved on **July 18, 2026**. It is frozen historical evidence for exploring this tool, not a source of current journey predictions. No original private household routes were reused.

Route inputs and attribution:

- Map data © [OpenStreetMap contributors](https://www.openstreetmap.org/copyright), under ODbL. The original OSM database is not bundled.
- Data provided by Chicago Transit Authority. [Developer terms](https://www.transitchicago.com/developers/terms/).
- Metra schedule data. This project is **not sponsored or operated by Metra**. [Data license](https://metra.com/sites/default/files/assets/developers/gtfs_license_agreement.pdf).
- Regional bus schedule data from [Pace's route timetable service](https://www.pacebus.com/route-timetable-data-services), subject to its data terms.

No transit agency sponsors, operates, or endorses this project. Agency marks and raw GTFS archives are not included. The source providers retain their rights; the software license does not relicense their data. Input SHA-256 hashes and feed coverage are recorded in `routes.json`. Obtain current inputs from the providers and check their terms before computing a real search.

The route request fingerprint in this portable example is bound to the packaged origin/destination/scenario configuration with an empty local network path. It validates reuse of these example results without access to the original machine. The separate provenance hashes identify the actual computational inputs.
