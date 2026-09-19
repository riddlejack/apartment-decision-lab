import json
from importlib.resources import files
import shutil
import subprocess

import pytest

from housing.browser import RECIPES, extraction_script


def generated_settings(script):
    return json.loads(script.rsplit(")(", 1)[1][:-1])


def test_packaged_reader_and_options_are_emitted_without_mutating_input():
    resource = files("housing").joinpath("browser_capture.js")
    assert resource.is_file() and resource.read_text(encoding="utf-8").startswith("(options) =>")
    options = {
        "source": "must-not-override",
        "recipe": "must-not-override",
        "limit": 17,
        "criteria": {"scope": "unfiltered"},
        "cards": ".listing",
        "link": "a.details",
    }
    original = json.loads(json.dumps(options))

    settings = generated_settings(extraction_script(
        "custom-assisted", "generic", "https://rentals.example/search", options,
    ))

    assert options == original
    assert settings == {
        **original,
        "source": "custom-assisted",
        "recipe": "generic",
        "search_url": "https://rentals.example/search",
    }
    assert set(RECIPES) == {
        "domu", "compass", "apartments", "zillow", "apartmentlist", "rentcafe", "generic",
    }


def test_script_defaults_to_no_claim_about_applied_criteria_and_rejects_bad_options():
    settings = generated_settings(extraction_script("domu-assisted", "domu"))
    assert settings["criteria"] == {}
    with pytest.raises(ValueError, match="JSON object"):
        extraction_script("domu-assisted", "domu", options=[])
    with pytest.raises(ValueError, match="Unknown browser recipe"):
        extraction_script("domu-assisted", "unknown")


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is optional")
def test_generated_script_is_valid_javascript_and_refuses_zero_cards():
    script = extraction_script(
        "custom-assisted",
        "generic",
        "https://rentals.example/search",
        {"cards": ".listing", "link": "a.details", "criteria": {"scope": "unfiltered"}},
    )
    program = f"""
const capture = eval({json.dumps(f'({script})')});
global.location = {{href: "https://rentals.example/search"}};
global.document = {{querySelectorAll: () => [], querySelector: () => null}};
try {{
  capture();
  console.error("zero-card capture unexpectedly succeeded");
  process.exit(2);
}} catch (error) {{
  if (!String(error.message).includes("found no cards")) {{
    console.error(error.stack || error.message);
    process.exit(3);
  }}
}}
"""
    completed = subprocess.run(
        [shutil.which("node"), "-e", program], capture_output=True, text=True, check=False,
    )
    assert completed.returncode == 0, completed.stderr
