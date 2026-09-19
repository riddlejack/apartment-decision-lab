from __future__ import annotations

import unittest

from housing.sources import default_sources, source_catalog


class SourceCatalogTests(unittest.TestCase):
    def test_chicago_has_runnable_breadth_and_visible_gaps(self) -> None:
        catalog = source_catalog("Chicago, IL")
        enabled = [source for source in catalog if source["enabled"]]
        self.assertGreaterEqual(len(enabled), 6)
        self.assertGreaterEqual(len({source["adapter"] for source in enabled}), 4)
        self.assertTrue(all(source["catalog_source"] is True for source in catalog))
        self.assertTrue(all({"id", "adapter", "permission_note", "max_pages", "max_listings", "search"} <= source.keys() for source in catalog))
        gaps = {source["id"] for source in catalog if source["adapter"] == "assisted"}
        self.assertTrue({"rentcafe-chicago-assisted", "domu-assisted", "apartment-list-assisted", "compass-assisted"} <= gaps)

    def test_default_sources_overlay_search_without_mutating_catalog(self) -> None:
        defaults = default_sources("Chicago", {"max_rent": 3000, "min_sqft": 900})
        self.assertTrue(defaults)
        self.assertTrue(all(source["search"]["max_rent"] == 3000 for source in defaults))
        self.assertTrue(all(source["search"]["min_sqft"] == 900 for source in defaults))
        self.assertTrue(all("max_rent" not in source["search"] for source in source_catalog("Chicago")))

    def test_unknown_city_does_not_block_custom_source_setup(self) -> None:
        catalog = source_catalog("Milwaukee, WI")
        self.assertEqual(default_sources("Milwaukee, WI"), [])
        self.assertEqual({source["adapter"] for source in catalog}, {"homeharvest", "assisted"})
        self.assertEqual(catalog[0]["search"]["location"], "Milwaukee, WI")


if __name__ == "__main__":
    unittest.main()
