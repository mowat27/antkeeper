# OTEL Coding Standards

Architectural policies and conventions for OpenTelemetry tracing in Python applications that export to Axiom. These standards guide span design, resource attribute naming, and Axiom ingestion behavior.

## Table of Contents

1. [TracerProvider ownership](#tracerprovider-ownership)
2. [Resource attributes and Axiom ingestion](#resource-attributes-and-axiom-ingestion)
3. [Span hierarchy design](#span-hierarchy-design)
4. [Span attribute conventions](#span-attribute-conventions)
5. [Two TracerProvider reality](#two-tracerprovider-reality)
6. [Signal handling](#signal-handling)
7. [Naming conventions](#naming-conventions)

---

## TracerProvider ownership

The Python application configures its own TracerProvider programmatically. This is not negotiable — `opentelemetry-instrument` cannot set resource attributes that are generated at runtime (like build IDs).

**Layering:**

| Layer | Responsibility |
|-------|---------------|
| Bash wrapper (`bin/run-*`) | Exporter env vars (endpoint, auth headers, protocol) |
| `with-otel` | CC subprocess telemetry configuration |
| Python app | TracerProvider with runtime resource attributes, span creation |

No layer configures another layer's TracerProvider. The bash wrapper sets env vars that the Python app reads when building the exporter. CC subprocesses inherit env vars and configure their own providers via `with-otel`.

---

## Resource attributes and Axiom ingestion

### The resource.custom reality

Axiom classifies resource attributes using OTEL semantic conventions (v1.21-v1.32). The behavior is:

| Attribute namespace | Axiom treatment | Example |
|--------------------|--------------------|---------|
| `service.*` | Flattened to `resource.service.name` | `service.name` |
| `host.*`, `os.*`, `deployment.*` | Flattened to `resource.host.arch` etc. | `host.arch` |
| Custom namespaces (`build.*`, `env.*`) | JSON blob in `resource.custom` | `build.id` |

**This is by design. It is not configurable. There is no header, setting, or workaround that changes this behavior for the Python OTEL SDK.**

CC spans get custom attributes flattened (e.g., `resource.build.id`) because CC uses a non-standard exporter that Axiom treats differently. This is a CC-specific behavior — not replicable from Python.

### Querying resource.custom

Custom resource attributes from Python spans are queryable via Axiom's map field syntax:

```apl
['resource.custom']['build.id'] == "abc123"
```

See `references/axiom-query-reference.md` for the unified query pattern that covers both Python and CC spans.

### Naming rules

- **Do not prefix with `resource.`** — Axiom adds `resource.` automatically. An attribute named `resource.branch.name` becomes `resource.resource.branch.name` (doubled prefix). Use `branch.name` instead.
- **Use dots for namespacing** — `build.id`, `build.app_name`, `branch.name`
- **Use `service.name`** for the application name — this is a recognized semconv attribute and gets flattened properly

---

## Span hierarchy design

Design spans as a tree reflecting logical containment, not call stack:

```
app.build                    (root — one per build)
  +-- app.import             (optional — setup phase)
  |    +-- app.import.step   (one per import step)
  +-- app.slice              (one per work unit)
  |    +-- library.run       (workflow execution)
  |         +-- library.step (one per step in workflow)
  |              +-- library.llm.call (LLM interaction)
  +-- app.checkpoint         (review boundary)
```

### Rules

- **One root span per logical operation** — a build, a deployment, a migration
- **Child spans for phases** — import, execution, checkpoint
- **Leaf spans for individual units of work** — steps, LLM calls
- **Span names use dot notation** — `app.slice`, not `app_slice` or `AppSlice`
- **Put the build.id on every span you create as a span attribute** — this is redundant with the resource attribute but ensures queryability via `attributes.custom['build.id']` as a fallback

---

## Span attribute conventions

### What goes on spans (attributes)

Per-span data that varies between spans of the same type:

- `slice.name` — which slice this is
- `slice.index` — position in the sequence
- `step.name` — which step (specify, implement, test, etc.)
- `checkpoint.number` — checkpoint sequence number
- `build.id` — redundant with resource, but ensures queryability

### What goes on resources

Process-level data that's the same for every span:

- `service.name` — application name
- `build.id` — build identifier
- `build.app_name` — application being built
- `branch.name` — git branch
- `env.workdir` — working directory

### Axiom field mapping

Both span attributes and resource attributes from the Python SDK land in `.custom` JSON blobs in Axiom:

| Source | Axiom location | Query syntax |
|--------|---------------|--------------|
| Resource attribute `build.id` | `resource.custom` | `['resource.custom']['build.id']` |
| Span attribute `build.id` | `attributes.custom` | `['attributes.custom']['build.id']` |
| CC resource attribute `build.id` | `resource.build.id` | `['resource.build.id']` |

---

## Two TracerProvider reality

A Python app that spawns CC subprocesses has **two separate trace contexts**:

1. **In-process** (Python) — all Python spans share one TracerProvider, one trace_id, correct parent-child via `contextvars`
2. **CC subprocesses** — each CC session is its own process with its own TracerProvider and its own trace_id

There is no trace context propagation between the Python process and CC subprocesses. The `build.id` resource attribute is the **only** thing that ties them together across separate traces.

This is why `build.id` must be set on both the Python TracerProvider (as a resource attribute) and in `OTEL_RESOURCE_ATTRIBUTES` (for CC subprocesses).

---

## Signal handling

**Every long-running Python process that creates OTEL spans MUST register signal handlers.** Without them, interrupted processes lose all open spans — they never flush to Axiom.

Required signals: SIGINT, SIGTERM, atexit.

The cleanup pattern:
1. End all open spans with ERROR status and an interrupt message
2. Force-flush the tracer provider with a timeout (5 seconds)
3. Exit with appropriate code (128 + signal number)

See `references/installation.md` Step 4 for the implementation.

---

## Naming conventions

| Convention | Example | Anti-pattern |
|-----------|---------|-------------|
| Span names: dot notation | `afk2.slice` | `afk2_slice`, `AFK2Slice` |
| Resource attrs: dot notation | `build.id` | `build_id`, `buildId` |
| No `resource.` prefix in attrs | `branch.name` | `resource.branch.name` (causes doubled prefix) |
| Scope name matches app | `trace.get_tracer("afk2")` | `trace.get_tracer("opentelemetry")` |
