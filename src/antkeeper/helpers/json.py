"""JSON extraction from LLM responses.

This module provides utilities for extracting and parsing JSON from text
that may be wrapped in markdown code fences or surrounded by prose, which
is common in LLM outputs.
"""

import json as _json


def json_prompt(prompt: str, *, required_fields: list[str]) -> str:
    """Append JSON output instructions and an example object to a prompt.

    Builds an example JSON object from the required field names and appends
    instructions telling the LLM to respond with only a JSON object.

    Args:
        prompt: The original prompt text.
        required_fields: Field names that must appear in the JSON response.

    Returns:
        The prompt with JSON instructions appended.
    """
    example = {field: f"<{field}>" for field in required_fields}
    return (
        f"{prompt}\n\n"
        f"After running the command, return ONLY a JSON object: "
        f"{_json.dumps(example)}"
    )


def extract_json(text: str) -> dict:
    """Extract and parse a JSON object from text that may contain markdown fencing or prose.

    Finds the first '{' and last '}' in the text, extracts the substring between
    them (inclusive), and parses it as JSON. This is useful for parsing LLM
    responses that include JSON wrapped in markdown code blocks or explanatory text.

    Args:
        text: Raw text potentially containing a JSON object wrapped in
              markdown code fences or surrounding prose.

    Returns:
        The parsed JSON object as a dictionary.

    Raises:
        ValueError: If no braces are found or the extracted text is not valid JSON.

    Example:
        >>> text = '```json\\n{"key": "value"}\\n```'
        >>> extract_json(text)
        {'key': 'value'}
        >>> extract_json('Here is some data: {"a": 1} and more text')
        {'a': 1}
    """
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"No JSON object found in text: {text!r}")
    candidate = text[start : end + 1]
    try:
        return _json.loads(candidate)
    except _json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON: {e}") from e
