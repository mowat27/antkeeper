"""Tests for the json_prompt function.

Verifies that json_prompt() correctly embeds the original prompt text,
includes all required field names, and appends a valid example JSON object.
"""

import json

from antkeeper.helpers.json import json_prompt


def test_json_prompt_includes_original_prompt():
    """Test that json_prompt() output contains the original prompt text."""
    result = json_prompt("Do the thing", required_fields=["name"])
    assert "Do the thing" in result


def test_json_prompt_includes_required_fields():
    """Test that json_prompt() output includes all required field names."""
    result = json_prompt("prompt", required_fields=["feature_type", "slug"])
    assert "feature_type" in result
    assert "slug" in result


def test_json_prompt_includes_example_json():
    """Test that json_prompt() appends a valid JSON example with required fields as keys."""
    result = json_prompt("prompt", required_fields=["name", "value"])
    # Extract the JSON portion after "return ONLY a JSON object: "
    marker = "return ONLY a JSON object: "
    idx = result.index(marker) + len(marker)
    parsed = json.loads(result[idx:])
    assert "name" in parsed
    assert "value" in parsed


def test_json_prompt_slash_command_instruction_comes_before_command():
    """For slash commands, the JSON instruction must precede the command.

    claude -p treats everything after the slash command name as $ARGUMENTS.
    Appending after \\n\\n would absorb the instruction into $ARGUMENTS, making
    it argument noise rather than a post-execution directive.  The instruction
    must appear before the slash command so it is outside $ARGUMENTS expansion.
    """
    result = json_prompt("/design-importer specify-slice arg1", required_fields=["spec_file"])
    instruction_pos = result.index("return ONLY a JSON object")
    command_pos = result.index("/design-importer")
    assert instruction_pos < command_pos, (
        "JSON instruction must precede the slash command to avoid being absorbed as $ARGUMENTS"
    )


def test_json_prompt_slash_command_contains_all_fields():
    """Slash command variant still includes all required field names."""
    result = json_prompt("/cmd arg", required_fields=["foo", "bar"])
    assert "foo" in result
    assert "bar" in result


def test_json_prompt_plain_prompt_instruction_comes_after():
    """For non-slash-command prompts, the JSON instruction is appended after."""
    result = json_prompt("Do the thing", required_fields=["name"])
    instruction_pos = result.index("return ONLY a JSON object")
    prompt_pos = result.index("Do the thing")
    assert prompt_pos < instruction_pos
