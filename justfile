default:
  @just --list

check: ruff ty test

ruff:
  uv run ruff check

ty:
  uv run ty check

test:
  uv run pytest

server:
  uv run antkeeper server

check_api host="127.0.0.1" port="8000":
  curl -s -X POST http://{{host}}:{{port}}/webhook \
    -H "Content-Type: application/json" \
    -d '{"workflow_name": "healthcheck"}' | python3 -m json.tool

release version:
  #!/usr/bin/env bash
  set -euo pipefail

  # Abort if working tree is dirty
  if [ -n "$(git status --porcelain)" ]; then
    echo "Error: working tree is not clean. Commit or stash your changes first."
    exit 1
  fi

  # Update version in pyproject.toml
  sed -i '' "s/^version = \".*\"/version = \"{{version}}\"/" pyproject.toml
  echo "Version set to {{version}}"

  # Run quality checks
  just check

  # Build and publish
  rm -rf dist/
  uv build
  uv publish

  # Commit, tag, and push
  git add pyproject.toml uv.lock
  git commit -m "release: v{{version}}"
  git tag "v{{version}}"
  git push && git push --tags
  echo "Published antkeeper {{version}} to PyPI"

sdlc prompt model="opus":
  #!/usr/bin/env bash
  if [ -f "{{prompt}}" ]; then
    uv run antkeeper run --model {{model}} sdlc "{{prompt}}"
  else
    echo "{{prompt}}" | uv run antkeeper run --model {{model}} sdlc
  fi

sdlc_iso prompt model="opus":
  #!/usr/bin/env bash
  if [ -f "{{prompt}}" ]; then
    uv run antkeeper run --model {{model}} sdlc_iso "{{prompt}}"
  else
    echo "{{prompt}}" | uv run antkeeper run --model {{model}} sdlc_iso
  fi
