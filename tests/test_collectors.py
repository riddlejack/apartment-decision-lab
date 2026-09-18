from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
import threading
import unittest
from unittest.mock import patch
from urllib.request import Request

from housing import collectors


OBSERVED = "2026-09-18T12:00:00Z"


APPFOLIO_HTML = """
<html><body>
  <div id="result_container" class="listings js-listings-container">
    <div class="listing-item result js-listing-item">
      <img alt="101 Example Avenue, Apt 4, Sample City, IA 50000">
      <dl>
        <div><dt>TOTAL MONTHLY PRICE</dt><dd>$1,875</dd></div>
        <div><dt>RENT</dt><dd>$1,800</dd></div>
        <div><dt>Bed / Bath</dt><dd>Studio / 1 ba</dd></div>
        <div><dt>Available</dt><dd>NOW</dd></div>
      </dl>
      <h2 class="listing-item__title"><a href="/listings/detail/unit-abc?source=site">Sunny studio</a></h2>
      <span class="js-listing-address">101 Example Avenue, Apt 4, Sample City, IA 50000</span>
      <a href="/listings/detail/unit-abc">View Details</a>
    </div>
    <div class="listing-item">
      <dl>
        <div><dt>RENT</dt><dd>$1,500 - $1,700</dd></div>
        <div><dt>Bed / Bath</dt><dd>2 bd / 1.5 ba</dd></div>
      </dl>
      <h2 class="listing-item__title"><a href="/listings/detail/unit-range">Range listing</a></h2>
      <span class="js-listing-address">202 Sample Street, Exampletown, IA 50001</span>
    </div>
  </div>
</body></html>
"""


MANAGEBUILDING_HTML = """
<html><body><div id="rentals-container" class="rentals">
  <a class="featured-listing card" href="/Resident/public/rentals/42017?campaign=x"
     data-bedrooms="3" data-bathrooms="2.5" data-rent="2450.00" data-type="MultiFamily">
    <h3 class="featured-listing__title">88 Fictional Road - 3B</h3>
    <p class="featured-listing__address">Exampletown, NM 87000</p>
    <p class="featured-listing__features">3 Bed | 2.5 Bath</p>
    <p class="featured-listing__price">$2,450</p>
    <p class="featured-listing__availability">available October 1</p>
  </a>
  <a class="featured-listing" href="/Resident/public/rentals/42018"
     data-type="SingleFamily">
    <h3 class="featured-listing__title">9 Imaginary Lane</h3>
    <p class="featured-listing__address">Sample City, NM 87001</p>
    <p class="featured-listing__features">Studio | 1 Bath</p>
    <p class="featured-listing__price">Call for rent</p>
  </a>
</div></body></html>
"""


def fetched(status: int, url: str, body: str, content_type: str = "text/html") -> collectors._Fetch:
    return collectors._Fetch(status, url, body.encode(), content_type, None if status == 200 else f"HTTP {status}")


class ParseTests(unittest.TestCase):
    def test_appfolio_keeps_card_grain_and_canonical_provider_id(self) -> None:
        rows = collectors.parse(
            "appfolio",
            APPFOLIO_HTML,
            "https://sample.appfolio.com/listings/listings",
            "sample-manager",
            observed_at=OBSERVED,
        )

        self.assertEqual(len(rows), 2)
        first = rows[0]
        self.assertEqual(first["id"], "sample-manager:unit-abc")
        self.assertEqual(first["source_id"], "unit-abc")
        self.assertEqual(first["url"], "https://sample.appfolio.com/listings/detail/unit-abc")
        self.assertEqual(first["rent"], 1800)
        self.assertEqual(first["total_monthly_cost"], 1875)
        self.assertEqual(first["bedrooms"], 0)
        self.assertEqual(first["bathrooms"], 1)
        self.assertEqual(first["grain"], "unit")
        self.assertIsNone(first["unit"])
        self.assertIsNone(first["lat"])
        self.assertEqual(first["observed_at"], OBSERVED)
        self.assertEqual(first["parser_version"], "appfolio-html-v1")
        self.assertEqual(first["source_content_sha256"], hashlib.sha256(APPFOLIO_HTML.encode()).hexdigest())
        self.assertIsNone(rows[1]["rent"], "a price range must not become a point rent")
        self.assertEqual(rows[1]["bedrooms"], 2)
        self.assertEqual(rows[1]["bathrooms"], 1.5)

    def test_appfolio_total_monthly_cost_never_substitutes_for_base_rent(self) -> None:
        html = """
        <div class="listing-item">
          <dl>
            <div><dt>TOTAL MONTHLY PRICE</dt><dd>$2,125</dd></div>
            <div><dt>Bed / Bath</dt><dd>1 bd / 1 ba</dd></div>
          </dl>
          <a href="/listings/detail/fees-only">Details</a>
        </div>
        """
        row = collectors.parse("appfolio", html, "https://sample.appfolio.com/listings", "sample", OBSERVED)[0]
        self.assertIsNone(row["rent"])
        self.assertEqual(row["total_monthly_cost"], 2125)
        self.assertIn("Base rent not reported", row["notes"])

    def test_managebuilding_uses_data_fields_and_conservative_grain(self) -> None:
        rows = collectors.parse(
            "managebuilding",
            MANAGEBUILDING_HTML,
            "https://sample.managebuilding.com/Resident/public/rentals",
            "another-manager",
            observed_at=OBSERVED,
        )

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["source_id"], "42017")
        self.assertEqual(rows[0]["address"], "88 Fictional Road, Exampletown, NM 87000")
        self.assertEqual(rows[0]["unit"], "3B")
        self.assertEqual(rows[0]["grain"], "unit")
        self.assertEqual(rows[0]["rent"], 2450)
        self.assertEqual(rows[0]["bedrooms"], 3)
        self.assertEqual(rows[0]["bathrooms"], 2.5)
        self.assertEqual(rows[1]["grain"], "property")
        self.assertIsNone(rows[1]["rent"])
        self.assertEqual(rows[1]["bedrooms"], 0)

    def test_unknown_adapter_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            collectors.parse("mystery", "<html></html>", "https://example.test", "source")

    def test_missing_card_text_remains_null(self) -> None:
        html = '<div class="listing-item"><a href="/listings/detail/only-id">Details</a></div>'
        row = collectors.parse("appfolio", html, "https://sample.appfolio.com/listings", "sample", OBSERVED)[0]
        self.assertIsNone(row["title"])
        self.assertIsNone(row["address"])
        self.assertIsNone(row["rent"])
        self.assertIsNone(row["bedrooms"])
        self.assertIsNone(row["bathrooms"])

    def test_authorized_json_feed_uses_documented_listing_schema(self) -> None:
        payload = json.dumps({"listings": [{
            "source_id": "owner-unit-7",
            "url": "/units/7?tracking=feed",
            "title": "Synthetic unit",
            "address": "7 Example Plaza",
            "unit": "7",
            "grain": "unit",
            "rent": 1600,
            "total_monthly_cost": 1665,
            "bedrooms": 2,
            "bathrooms": 1.5,
            "lat": 35.1,
            "lon": -106.6,
            "historical": False
        }]})
        row = collectors.parse("json", payload, "https://feed.example/listings.json", "owner-feed", OBSERVED)[0]
        self.assertEqual(row["id"], "owner-feed:owner-unit-7")
        self.assertEqual(row["url"], "https://feed.example/units/7")
        self.assertEqual(row["rent"], 1600)
        self.assertEqual(row["total_monthly_cost"], 1665)
        self.assertEqual((row["lat"], row["lon"]), (35.1, -106.6))
        self.assertEqual(row["observed_at"], OBSERVED)
        self.assertEqual(row["parser_version"], "json-feed-v1")
        self.assertEqual(row["source_content_sha256"], hashlib.sha256(payload.encode()).hexdigest())

    def test_json_feed_rejects_duplicate_provider_ids(self) -> None:
        payload = json.dumps([{"source_id": "same"}, {"source_id": "same"}])
        with self.assertRaisesRegex(ValueError, "duplicate JSON source_id"):
            collectors.parse("json", payload, "https://feed.example/listings.json", "owner-feed", OBSERVED)


class _SyntheticFeedHandler(BaseHTTPRequestHandler):
    paths: list[str] = []
    feed = json.dumps({"listings": [{
        "source_id": "synthetic-101",
        "url": "/units/101?from=feed",
        "title": "Owner supplied synthetic apartment",
        "address": "101 Example Avenue",
        "unit": "2A",
        "grain": "unit",
        "rent": 1450,
        "total_monthly_cost": 1505,
        "bedrooms": 1,
        "bathrooms": 1,
        "lat": None,
        "lon": None,
        "historical": False
    }]})

    def do_GET(self) -> None:  # noqa: N802
        type(self).paths.append(self.path)
        if self.path == "/robots.txt":
            body = b"User-agent: housing-decision-lab\nAllow: /feed.json\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
        elif self.path == "/feed.json":
            body = self.feed.encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
        else:
            body = b"not found"
            self.send_response(404)
            self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        pass


class CollectionTests(unittest.TestCase):
    SOURCE = {
        "id": "sample-manager",
        "adapter": "appfolio",
        "url": "https://sample.appfolio.com/listings/listings",
        "enabled": True,
        "permission_note": "The feed owner authorized automated retrieval of this exact endpoint on 2026-09-18.",
    }

    def test_disabled_and_missing_permission_make_no_requests(self) -> None:
        with patch.object(collectors, "_fetch_url") as fetch:
            disabled = collectors.collect_source({**self.SOURCE, "enabled": False})
            missing = collectors.collect_source({**self.SOURCE, "permission_note": ""})
        self.assertEqual((disabled["status"], disabled["requests"]), ("error", 0))
        self.assertEqual((missing["status"], missing["requests"]), ("error", 0))
        fetch.assert_not_called()

    def test_robots_disallow_stops_before_listing_page(self) -> None:
        robots = "User-agent: *\nDisallow: /listings/\n"
        with patch.object(
            collectors,
            "_fetch_url",
            return_value=fetched(200, "https://sample.appfolio.com/robots.txt", robots, "text/plain"),
        ) as fetch:
            result = collectors.collect_source(self.SOURCE)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["requests"], 1)
        self.assertEqual(fetch.call_count, 1)

    def test_success_is_one_page_and_reports_unhandled_pagination(self) -> None:
        page = APPFOLIO_HTML.replace("</body>", '<a rel="next" href="?page=2">Next</a></body>')
        responses = [
            fetched(200, "https://sample.appfolio.com/robots.txt", "User-agent: *\nAllow: /\n", "text/plain"),
            fetched(200, self.SOURCE["url"], page),
        ]
        with patch.object(collectors, "_fetch_url", side_effect=responses) as fetch:
            result = collectors.collect_source(self.SOURCE)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["requests"], 2)
        self.assertEqual(len(result["listings"]), 2)
        self.assertTrue(result["partial"])
        self.assertIn("pagination", result["message"])
        self.assertEqual(fetch.call_count, 2, "robots plus exactly one listings page")

    def test_explicit_empty_is_distinct_from_changed_markup(self) -> None:
        robots = fetched(200, "https://sample.managebuilding.com/robots.txt", "User-agent: *\nAllow: /\n", "text/plain")
        empty_html = '<div id="rentals-container">There are no available rentals at this time. Please check back again later.</div>'
        source = {**self.SOURCE, "adapter": "managebuilding", "url": "https://sample.managebuilding.com/Resident/public/rentals"}
        with patch.object(collectors, "_fetch_url", side_effect=[robots, fetched(200, source["url"], empty_html)]):
            empty = collectors.collect_source(source)
        with patch.object(collectors, "_fetch_url", side_effect=[robots, fetched(200, source["url"], "<html><h1>Rentals</h1></html>")]):
            changed = collectors.collect_source(source)
        self.assertEqual(empty["status"], "empty")
        self.assertEqual(changed["status"], "error")
        self.assertIn("markup may have changed", changed["message"])

    def test_rate_limit_and_challenge_are_blocked_without_bypass(self) -> None:
        robots = fetched(200, "https://sample.appfolio.com/robots.txt", "User-agent: *\nAllow: /\n", "text/plain")
        with patch.object(collectors, "_fetch_url", side_effect=[robots, fetched(429, self.SOURCE["url"], "slow down")]):
            limited = collectors.collect_source(self.SOURCE)
        with patch.object(
            collectors,
            "_fetch_url",
            side_effect=[robots, fetched(200, self.SOURCE["url"], "<html>Verify you are human</html>")],
        ):
            challenged = collectors.collect_source(self.SOURCE)
        self.assertEqual(limited["status"], "blocked")
        self.assertEqual(challenged["status"], "blocked")

    def test_cross_host_redirect_is_not_collected_under_original_robots_policy(self) -> None:
        robots = fetched(200, "https://sample.appfolio.com/robots.txt", "User-agent: *\nAllow: /\n", "text/plain")
        redirected = fetched(200, "https://different.example/listings", APPFOLIO_HTML)
        with patch.object(collectors, "_fetch_url", side_effect=[robots, redirected]):
            result = collectors.collect_source(self.SOURCE)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["requests"], 2)
        self.assertIn("different host", result["message"])

    def test_http_redirect_handler_does_not_follow_another_request(self) -> None:
        handler = collectors._NoRedirect()
        followup = handler.redirect_request(
            Request(self.SOURCE["url"]),
            None,
            302,
            "Found",
            {"Location": "https://different.example/listings"},
            "https://different.example/listings",
        )
        self.assertIsNone(followup)

    def test_json_adapter_collects_owner_authorized_local_feed_end_to_end(self) -> None:
        _SyntheticFeedHandler.paths = []
        server = ThreadingHTTPServer(("127.0.0.1", 0), _SyntheticFeedHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}/feed.json"
            result = collectors.collect_source({
                "id": "synthetic-owner-feed",
                "adapter": "json",
                "url": url,
                "enabled": True,
                "permission_note": "The local feed owner authorized this exact endpoint for automated retrieval.",
            })
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["requests"], 2)
        self.assertEqual(_SyntheticFeedHandler.paths, ["/robots.txt", "/feed.json"])
        self.assertEqual(len(result["listings"]), 1)
        self.assertEqual(result["listings"][0]["id"], "synthetic-owner-feed:synthetic-101")
        self.assertEqual(result["listings"][0]["rent"], 1450)
        self.assertEqual(result["listings"][0]["total_monthly_cost"], 1505)


if __name__ == "__main__":
    unittest.main()
