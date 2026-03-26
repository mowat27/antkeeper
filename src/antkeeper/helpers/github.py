"""GitHub CLI helpers for handler use."""

import json
import subprocess


def fetch_gh_issue(issue_number: int) -> dict:
    """Fetch a GitHub issue via the gh CLI.

    Args:
        issue_number: The GitHub issue number to fetch.

    Returns:
        dict: Parsed JSON response from gh containing issue details.

    Raises:
        FileNotFoundError: If gh CLI is not installed.
        subprocess.CalledProcessError: If gh command fails.
        json.JSONDecodeError: If gh response is not valid JSON.
    """
    result = subprocess.run(
        [
            "gh",
            "issue",
            "view",
            str(issue_number),
            "--json",
            "number,title,body,comments,labels,state",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def build_issues_prompt(issues: list[dict]) -> str:
    """Build a prompt from a list of GitHub issues.

    Args:
        issues: List of issue dictionaries from fetch_gh_issue.

    Returns:
        str: Formatted prompt containing all issues.
    """
    parts = ["Fix the following GitHub issue(s).\n"]
    for issue in issues:
        parts.append(f"--- Issue #{issue['number']} ---\n")
        parts.append(json.dumps(issue, indent=2))
        parts.append("\n\n")
    return "".join(parts)
