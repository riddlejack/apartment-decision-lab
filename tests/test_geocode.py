from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib import error, parse

from housing import geocode


class _Response:
    def __init__(self, payload: bytes):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size: int) -> bytes:
        return self.payload[:size]


def census_response(matches: list[dict]) -> bytes:
    return json.dumps({"result": {"addressMatches": matches}}).encode()


class GeocodeTests(unittest.TestCase):
    def test_fetches_valid_match_and_uses_expected_query(self) -> None:
        body = census_response([{
            "matchedAddress": "4600 SILVER HILL RD, WASHINGTON, DC, 20233",
            "coordinates": {"x": -76.92744, "y": 38.84599},
        }])
        with tempfile.TemporaryDirectory() as directory, patch.object(
            geocode.request, "urlopen", return_value=_Response(body)
        ) as fetch:
            result = geocode.geocode_address("  4600 Silver Hill Rd, Washington DC 20233  ", Path(directory))

        req = fetch.call_args.args[0]
        query = parse.parse_qs(parse.urlsplit(req.full_url).query)
        self.assertEqual(query["address"], ["4600 Silver Hill Rd, Washington DC 20233"])
        self.assertEqual(query["benchmark"], ["Public_AR_Current"])
        self.assertEqual(fetch.call_args.kwargs["timeout"], 20)
        self.assertEqual(result["provider"], "US Census")
        self.assertFalse(result["cached"])
        self.assertIsNone(result["cache_age_seconds"])
        self.assertEqual(result["matches"][0]["lat"], 38.84599)
        self.assertEqual(result["matches"][0]["lon"], -76.92744)

    def test_second_call_uses_hashed_cache_and_reports_age(self) -> None:
        body = census_response([{
            "matchedAddress": "100 EXAMPLE AVE, SAMPLE CITY, IA, 50000",
            "coordinates": {"x": -93.5, "y": 41.6},
        }])
        with tempfile.TemporaryDirectory() as directory:
            cache_dir = Path(directory)
            with patch.object(geocode.request, "urlopen", return_value=_Response(body)) as fetch:
                first = geocode.geocode_address("100 Example Ave", cache_dir)
                second = geocode.geocode_address("100 Example Ave", cache_dir)
            files = list(cache_dir.iterdir())
            cache_mode = files[0].stat().st_mode & 0o777

        self.assertEqual(fetch.call_count, 1)
        self.assertFalse(first["cached"])
        self.assertTrue(second["cached"])
        self.assertGreaterEqual(second["cache_age_seconds"], 0)
        self.assertEqual(second["fetched_at"], first["fetched_at"])
        self.assertEqual(len(files), 1)
        self.assertNotIn("Example", files[0].name)
        self.assertEqual(cache_mode, 0o600)

    def test_no_match_is_an_empty_list_not_zero_coordinates(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.object(
            geocode.request, "urlopen", return_value=_Response(census_response([]))
        ):
            result = geocode.geocode_address("Unmatched synthetic address", Path(directory))
        self.assertEqual(result["matches"], [])

    def test_invalid_coordinates_fail_and_are_not_cached(self) -> None:
        body = census_response([{
            "matchedAddress": "INVALID SYNTHETIC ADDRESS",
            "coordinates": {"x": 0, "y": 0},
        }])
        with tempfile.TemporaryDirectory() as directory, patch.object(
            geocode.request, "urlopen", return_value=_Response(body)
        ):
            cache_dir = Path(directory)
            with self.assertRaisesRegex(RuntimeError, "invalid coordinates"):
                geocode.geocode_address("Invalid synthetic address", cache_dir)
            self.assertEqual(list(cache_dir.iterdir()), [])

    def test_input_limit_is_checked_before_network(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.object(geocode.request, "urlopen") as fetch:
            with self.assertRaisesRegex(ValueError, "500 characters"):
                geocode.geocode_address("x" * 501, Path(directory))
        fetch.assert_not_called()

    def test_oversized_response_is_rejected(self) -> None:
        body = b"x" * (geocode.MAX_RESPONSE_BYTES + 1)
        with tempfile.TemporaryDirectory() as directory, patch.object(
            geocode.request, "urlopen", return_value=_Response(body)
        ):
            with self.assertRaisesRegex(RuntimeError, "exceeded 1 MiB"):
                geocode.geocode_address("Oversized synthetic response", Path(directory))

    def test_network_error_never_echoes_input_address(self) -> None:
        private_input = "123 Private Test Street"
        failure = error.URLError(private_input)
        with tempfile.TemporaryDirectory() as directory, patch.object(
            geocode.request, "urlopen", side_effect=failure
        ):
            with self.assertRaises(RuntimeError) as raised:
                geocode.geocode_address(private_input, Path(directory))
        self.assertNotIn(private_input, str(raised.exception))

    def test_cache_write_failure_is_explicit_without_echoing_address(self) -> None:
        private_input = "900 Private Test Avenue"
        with tempfile.TemporaryDirectory() as directory, patch.object(
            geocode.request, "urlopen", return_value=_Response(census_response([]))
        ), patch.object(geocode, "_write_cache", side_effect=OSError(private_input)):
            with self.assertRaisesRegex(RuntimeError, "cache could not be written") as raised:
                geocode.geocode_address(private_input, Path(directory))
        self.assertNotIn(private_input, str(raised.exception))


if __name__ == "__main__":
    unittest.main()
