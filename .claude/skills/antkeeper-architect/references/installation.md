# Antkeeper Installation

## Steps

1. [Install the package](#step-1--install-the-package)
2. [Scaffold a project](#step-2--scaffold-a-project)
3. [Verify the setup](#step-3--verify-the-setup)
4. [Fetch version-matched documentation](#step-4--fetch-version-matched-documentation)

---

## Step 1 — Install the package

Install the latest antkeeper from PyPI using uv.

```bash
uv add antkeeper
```

**What this provides:** The `antkeeper` CLI command and the full framework library (`antkeeper.core`, `antkeeper.channels`, `antkeeper.handlers`, `antkeeper.llm`, `antkeeper.git`, `antkeeper.helpers`).

**What this does NOT require:** No separate installation of FastAPI, Click, or OpenTelemetry — these are core dependencies bundled with antkeeper.

---

## Step 2 — Scaffold a project

Run the init command to generate a starter `handlers.py` with a working healthcheck handler and commented examples.

```bash
uv run antkeeper init .
```

This creates a `handlers.py` in the target directory containing:
- An `App` instance
- A `healthcheck` handler (smoke-test that calls the LLM)
- Commented examples of `cc_handler` factory usage and workflow composition

To scaffold into a new directory:

```bash
uv run antkeeper init my-project
cd my-project
```

**What this provides:** A working project that can immediately run `uv run antkeeper run healthcheck`.

---

## Step 3 — Verify the setup

Run the healthcheck workflow to confirm the LLM backend is reachable.

```bash
uv run antkeeper run healthcheck
```

You should see progress messages and a poem in the output. If using a specific model:

```bash
uv run antkeeper run --model sonnet healthcheck
```

**What this verifies:** The antkeeper CLI works, the handlers file loads correctly, and the Claude Code CLI is installed and accessible.

---

## Step 4 — Fetch version-matched documentation

Determine the installed version:

```bash
uv pip show antkeeper | grep Version
```

Then fetch the upstream documentation from the matching release tag. For example, if version `0.1.2` is installed:

```
https://raw.githubusercontent.com/mowat27/antkeeper/v0.1.2/README.md
https://raw.githubusercontent.com/mowat27/antkeeper/v0.1.2/app_docs/reference.md
```

These two files contain the complete usage guide and API reference for the installed version.

**What this provides:** Version-accurate documentation that matches the installed package exactly, avoiding drift between docs and code.

---

## Verification Checklist

Run these after completing all steps:

- [ ] `uv run antkeeper --version` prints the installed version
- [ ] `handlers.py` exists and contains an `app = App()` instance
- [ ] `uv run antkeeper run healthcheck` completes without errors
- [ ] A log file appears in `agents/logs/` after the healthcheck run
- [ ] A state file appears in `.antkeeper/state/` after the healthcheck run
