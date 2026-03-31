# Axiom Query Reference

Exact dataset schema, canonical query patterns, and field names for the `claude-code` dataset. **Read this file before writing any Axiom APL query.** Do not guess field names — every query referencing a nonexistent field wastes tokens and returns an error.

## Table of Contents

1. [Dataset schema](#dataset-schema)
2. [Unified build query](#unified-build-query)
3. [Canonical query patterns](#canonical-query-patterns)
4. [Field access rules](#field-access-rules)
5. [Common gotchas](#common-gotchas)
6. [Fields that DO NOT EXIST](#fields-that-do-not-exist)

---

## Dataset schema

Dataset: `claude-code`

### Top-level fields

| Field | Type | Description |
|-------|------|-------------|
| `_time` | datetime | Event timestamp |
| `_sysTime` | datetime | Axiom ingestion timestamp |
| `name` | string | Span name (e.g. `afk2.build`, `antkeeper.workflow.step`) |
| `body` | string | Event body (e.g. `claude_code.user_prompt`, `claude_code.api_request`) |
| `duration` | duration | Span duration (e.g. `2h32m49s`, `1m39s`) |
| `kind` | string | Span kind (`internal`, `client`, `server`) |
| `trace_id` | string | Trace identifier |
| `span_id` | string | Span identifier |
| `parent_span_id` | string | Parent span identifier |
| `status.code` | string | Span status (`OK`, `ERROR`, `UNSET`) |
| `status.message` | string | Status message (error details) |
| `service.name` | string | Service name from resource |

### Flattened resource fields (from CC spans)

These exist as top-level columns because CC's exporter gets special treatment from Axiom. **Only CC spans populate these fields.** Python SDK spans put the same data in `resource.custom`.

| Field | Type | Source |
|-------|------|--------|
| `resource.build.id` | string | Build identifier |
| `resource.build.app_name` | string | Application name |
| `resource.build.design_package` | string | Design package path |
| `resource.env.workdir` | string | Working directory |
| `resource.resource.branch.name` | string | Git branch (note: doubled `resource.` prefix — legacy naming bug) |
| `resource.host.arch` | string | CPU architecture (CC spans only) |
| `resource.os.type` | string | Operating system (CC spans only) |
| `resource.os.version` | string | OS version (CC spans only) |
| `resource.telemetry.auto.version` | string | Auto-instrumentation version |

### resource.custom (map field — Python SDK spans)

Python SDK spans put custom resource attributes here as a JSON object. Access with bracket syntax.

| Key | Type | Description |
|-----|------|-------------|
| `build.id` | string | Build identifier |
| `build.app_name` | string | Application name |
| `branch.name` | string | Git branch |
| `env.workdir` | string | Working directory |

**Query syntax:** `['resource.custom']['build.id']`

### Flattened span attribute fields

| Field | Type | Description |
|-------|------|-------------|
| `attributes.session.id` | string | CC session identifier |
| `attributes.model` | string | LLM model used (`claude-opus-4-6`, `claude-sonnet-4-6`, `claude-haiku-4-5-20251001`) |
| `attributes.cost_usd` | number | Cost per LLM call (use `toreal()` when aggregating) |
| `attributes.input_tokens` | number | Uncached input tokens (use `tolong()`) |
| `attributes.output_tokens` | number | Output tokens (use `tolong()`) |
| `attributes.cache_read_tokens` | number | Tokens served from cache (use `tolong()`) |
| `attributes.cache_creation_tokens` | number | Tokens written to cache (use `tolong()`) |
| `attributes.tool_name` | string | Tool invoked (Read, Write, Bash, Edit, etc.) |

### attributes.custom (map field — Python SDK spans)

Python SDK spans put custom span attributes here as a JSON object.

For **AFK2 spans** (`afk2.build`, `afk2.slice`, etc.):

| Key | Type | Description |
|-----|------|-------------|
| `build.id` | string | Build identifier |
| `build.app_name` | string | Application name |
| `build.manifest` | string | Manifest file path (on `afk2.build` only) |
| `build.slice_count` | number | Total slices (on `afk2.build` only) |
| `slice.name` | string | Slice name (on `afk2.slice` only) |
| `slice.index` | number | Slice position (on `afk2.slice` only) |

For **Antkeeper spans** (`antkeeper.workflow.step`, `antkeeper.run`):

| Key | Type | Description |
|-----|------|-------------|
| `run_id` | string | Antkeeper run identifier |
| `workflow_name` | string | Workflow name |
| `step_name` | string | Step label (e.g. "Specify slice", "Implement from spec") |
| `step_index` | number | Step position in workflow |
| `step_total` | number | Total steps in workflow |

**Query syntax:** `['attributes.custom']['step_name']`

---

## Unified build query

To get ALL spans for a build across both Python and CC sources:

```apl
['claude-code']
| where ['resource.build.id'] == "{BUILD_ID}"
   or ['resource.custom']['build.id'] == "{BUILD_ID}"
```

This covers:
- CC spans (via `resource.build.id`)
- Python SDK spans (via `resource.custom['build.id']`)

---

## Canonical query patterns

### All structural spans for a build

```apl
['claude-code']
| where (name startswith "afk2" or name startswith "antkeeper")
   and ['resource.custom']['build.id'] == "{BUILD_ID}"
| project name, duration, ['status.code'],
   ['attributes.custom']['slice.name'],
   ['attributes.custom']['step_name'],
   _time
| order by _time asc
```

### Per-step timing breakdown

```apl
['claude-code']
| where name == "antkeeper.workflow.step"
   and ['resource.custom']['build.id'] == "{BUILD_ID}"
| project
   step_name=['attributes.custom']['step_name'],
   workflow=['attributes.custom']['workflow_name'],
   duration, _time
| order by _time asc
```

### Cost and token summary by model

```apl
['claude-code']
| where ['resource.build.id'] == "{BUILD_ID}"
   and isnotnull(['attributes.cost_usd'])
| summarize
   calls=count(),
   total_cost=sum(toreal(['attributes.cost_usd'])),
   total_output=sum(tolong(['attributes.output_tokens'])),
   total_cache_read=sum(tolong(['attributes.cache_read_tokens']))
  by tostring(['attributes.model'])
```

### Tool usage breakdown

```apl
['claude-code']
| where ['resource.build.id'] == "{BUILD_ID}"
   and isnotnull(['attributes.tool_name'])
| summarize calls=count()
  by tostring(['attributes.tool_name'])
| order by calls desc
```

### Cost over time

```apl
['claude-code']
| where ['resource.build.id'] == "{BUILD_ID}"
   and isnotnull(['attributes.cost_usd'])
| summarize total_cost=sum(toreal(['attributes.cost_usd'])), calls=count()
  by bin_auto(_time)
| order by _time asc
```

### Per-session breakdown (one session = one Antkeeper step)

```apl
['claude-code']
| where ['resource.build.id'] == "{BUILD_ID}"
   and isnotnull(['attributes.session.id'])
| summarize
   min_time=min(_time),
   max_time=max(_time),
   calls=count(),
   cost=sum(toreal(['attributes.cost_usd']))
  by tostring(['attributes.session.id'])
| order by min_time asc
```

### Find a build by time range (when build ID is unknown)

```apl
['claude-code']
| where name == "afk2.build"
   and _time > datetime(2026-03-25T21:00:00Z)
   and _time < datetime(2026-03-26T00:00:00Z)
| project ['resource.custom']['build.id'], duration, ['status.code'], _time
```

---

## Field access rules

### Dotted field names must be bracket-quoted

```apl
-- CORRECT:
['resource.build.id']
['attributes.cost_usd']
['status.code']

-- WRONG (will error):
resource.build.id
attributes.cost_usd
status.code
```

Exception: `_time`, `name`, `body`, `duration`, `kind` — these are bare fields.

### Map field access uses double brackets

```apl
-- CORRECT:
['resource.custom']['build.id']
['attributes.custom']['step_name']

-- WRONG:
['resource.custom.build.id']
resource.custom['build.id']
```

### Numeric fields need type casting in aggregations

```apl
-- CORRECT:
sum(toreal(['attributes.cost_usd']))
sum(tolong(['attributes.output_tokens']))

-- WRONG (will produce incorrect results or errors):
sum(['attributes.cost_usd'])
sum(['attributes.output_tokens'])
```

### Grouping by string fields needs tostring()

```apl
-- CORRECT:
by tostring(['attributes.model'])

-- WRONG:
by ['attributes.model']
```

### _time must be in project if used in order by

```apl
-- CORRECT:
| project name, duration, _time
| order by _time asc

-- WRONG:
| project name, duration
| order by _time asc     <-- error: _time is not projected
```

---

## Common gotchas

1. **`resource.resource.branch.name`** — the doubled prefix is a legacy naming bug. The env var sets `resource.branch.name` as the attribute name, then Axiom prepends `resource.`. This only affects CC spans. Python spans use `['resource.custom']['branch.name']`.

2. **Structural spans have no `resource.build.id`** — use `['resource.custom']['build.id']` for `afk2.*` and `antkeeper.*` spans.

3. **CC LLM/tool spans have no `attributes.custom`** — CC spans use flattened `attributes.model`, `attributes.cost_usd`, etc. Don't try to access `['attributes.custom']['model']` on CC spans.

4. **`search "text"` is expensive** — use as a last resort to find which field contains a value. Prefer specific field queries.

5. **AFK2 structural spans flush only on completion** — a running build won't show its `afk2.build` span. CC spans flush in near-real-time. Check cost/token data from CC spans to monitor a running build.

6. **`isnotnull()` is your friend** — many fields are only populated on specific span types. Use `isnotnull(['attributes.cost_usd'])` to filter to LLM call spans, `isnotnull(['attributes.tool_name'])` for tool spans.

---

## Fields that DO NOT EXIST

These field names have been tried and failed. Do not use them:

| Attempted field | Why it fails | Use instead |
|----------------|-------------|-------------|
| `attributes.build.id` | Custom attrs go to `attributes.custom` | `['attributes.custom']['build.id']` |
| `attributes.slice.name` | Same reason | `['attributes.custom']['slice.name']` |
| `attributes.step_name` | Same reason | `['attributes.custom']['step_name']` |
| `attributes.custom.prompt` | Wrong syntax for map field | `['attributes.custom']['prompt']` |
| `resource.build.id` (on Python spans) | Custom resource attrs go to `resource.custom` | `['resource.custom']['build.id']` |
| `resource.branch.name` | Not a top-level field | `['resource.resource.branch.name']` (CC) or `['resource.custom']['branch.name']` (Python) |
| `service.name` (bare) | Must be quoted | `['service.name']` |
