"""Tests for the json_prompt function."""

import json

from antkeeper.helpers.json import json_prompt


def test_json_prompt_includes_original_prompt():
    result = json_prompt("Do the thing", required_fields=["name"])
    assert "Do the thing" in result


def test_json_prompt_includes_required_fields():
    result = json_prompt("prompt", required_fields=["feature_type", "slug"])
    assert "feature_type" in result
    assert "slug" in result


def test_json_prompt_includes_example_json():
    result = json_prompt("prompt", required_fields=["name", "value"])
    # Extract the JSON portion after "return ONLY a JSON object: "
    marker = "return ONLY a JSON object: "
    idx = result.index(marker) + len(marker)
    parsed = json.loads(result[idx:])
    assert "name" in parsed
    assert "value" in parsed
