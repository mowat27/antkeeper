"""Helper utilities for Antkeeper framework.

Provides utility functions for common tasks in Antkeeper workflows, including
JSON extraction from LLM responses and timestamp/log-directory helpers.

Public API:
    extract_json: Extract and parse JSON embedded in text or markdown.
    json_prompt: Return a prompt fragment instructing an LLM to emit JSON.
    make_timestamp: Return the current time as a YYYYMMDDHHmmss string.
    make_log_dir: Return a callable producing log directory paths for runners.
"""

from antkeeper.helpers.json import extract_json, json_prompt
from antkeeper.helpers.timestamps import make_log_dir, make_timestamp

__all__ = ["extract_json", "json_prompt", "make_log_dir", "make_timestamp"]
