# OTEL Installation Reference

Step-by-step procedure for adding OpenTelemetry tracing to a Python application that exports to Axiom. The pattern uses a programmatic TracerProvider (not `opentelemetry-instrument`) because build-specific resource attributes like `build.id` are only known at runtime.

## Table of Contents

1. [Python dependencies](#step-1--python-dependencies)
2. [Bash wrapper for exporter config](#step-2--bash-wrapper-for-exporter-config)
3. [Programmatic TracerProvider](#step-3--programmatic-tracerprovider)
4. [Signal handling for span flushing](#step-4--signal-handling-for-span-flushing)
5. [CC subprocess resource attributes](#step-5--cc-subprocess-resource-attributes)
6. [Verification checklist](#verification-checklist)

---

## Step 1 — Python dependencies

Add OpenTelemetry SDK and OTLP HTTP exporter:

```
opentelemetry-api
opentelemetry-sdk
opentelemetry-exporter-otlp-proto-http
```

### What this provides

- `opentelemetry.trace` — tracer API for creating spans
- `opentelemetry.sdk.trace` — TracerProvider and BatchSpanProcessor
- `opentelemetry.sdk.resources` — Resource for attaching metadata to all spans
- `opentelemetry.exporter.otlp.proto.http.trace_exporter` — OTLP HTTP exporter for Axiom

### What this does NOT require

- `opentelemetry-instrument` CLI — we configure the TracerProvider programmatically
- `opentelemetry-instrumentation-*` packages — auto-instrumentation is not used
- gRPC dependencies — we use HTTP/protobuf, not gRPC

---

## Step 2 — Bash wrapper for exporter config

Create a bash wrapper that sets Axiom exporter env vars, then launches the Python app wrapped with `with-otel` (for CC subprocess telemetry):

```bash
#!/usr/bin/env bash
set -e

# Fetch Axiom credentials (adapt to your secret management)
AXIOM_API_TOKEN="${AXIOM_API_TOKEN:-$(your-secret-fetch-command)}"
AXIOM_LOGS_DATASET="${AXIOM_LOGS_DATASET:-your-dataset}"

if [ -z "$AXIOM_API_TOKEN" ]; then
  echo >&2 "warning: AXIOM_API_TOKEN unavailable, running without OTEL"
  exec python3 your-app.py "$@"
fi

export OTEL_EXPORTER_OTLP_ENDPOINT="https://api.axiom.co"
export OTEL_EXPORTER_OTLP_TRACES_ENDPOINT="https://api.axiom.co/v1/traces"
export OTEL_EXPORTER_OTLP_TRACES_PROTOCOL="http/protobuf"
export OTEL_EXPORTER_OTLP_TRACES_HEADERS="Authorization=Bearer ${AXIOM_API_TOKEN},X-Axiom-Dataset=${AXIOM_LOGS_DATASET}"

exec with-otel python3 your-app.py "$@"
```

### Why two layers

- **Bash wrapper** sets exporter env vars (endpoint, auth headers). Static config — known before the process starts.
- **Python app** configures the TracerProvider programmatically after generating dynamic resource attributes (build IDs, app names). These aren't known until runtime.
- **`with-otel`** wraps the process so Claude Code subprocesses get their own telemetry configured.

### What this does NOT include

- `opentelemetry-instrument` — not in the exec chain. The Python app manages its own TracerProvider.

---

## Step 3 — Programmatic TracerProvider

In the Python app, configure the TracerProvider after generating any runtime identifiers:

```python
import os
from opentelemetry import trace
from opentelemetry.trace import StatusCode
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter


def configure_telemetry(build_id: str, app_name: str, extra_attrs: dict = None):
    """Configure TracerProvider with runtime resource attributes.

    Uses Resource() directly (not Resource.create()) to avoid SDK defaults.
    """
    attrs = {
        "service.name": app_name,
        "build.id": build_id,
        "build.app_name": app_name,
    }
    if extra_attrs:
        attrs.update(extra_attrs)

    resource = Resource(attrs)
    provider = TracerProvider(resource=resource)

    # Read exporter config from env (set by the bash wrapper)
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
    headers_str = os.environ.get("OTEL_EXPORTER_OTLP_TRACES_HEADERS", "")
    headers = {}
    if headers_str:
        for pair in headers_str.split(","):
            if "=" in pair:
                k, v = pair.split("=", 1)
                headers[k.strip()] = v.strip()

    if endpoint:
        exporter = OTLPSpanExporter(endpoint=endpoint, headers=headers)
        provider.add_span_processor(BatchSpanProcessor(exporter))

    trace.set_tracer_provider(provider)
    return trace.get_tracer("your-app")
```

### Why programmatic, not opentelemetry-instrument

`opentelemetry-instrument` configures the TracerProvider before the Python app starts. Resource attributes set via `OTEL_RESOURCE_ATTRIBUTES` must be known before process launch. Dynamic attributes (build IDs generated at runtime) can't be set this way — the TracerProvider is already configured by the time they exist.

### Important: Axiom's resource.custom behavior

Axiom classifies resource attributes using OTEL semantic conventions. Recognized namespaces (`service.*`, `host.*`, `os.*`, `deployment.*`, etc.) get flattened into top-level columns like `resource.service.name`. Custom namespaces like `build.*` go into `resource.custom` as a JSON map field. This is by design — not a bug, not configurable. See `references/axiom-query-reference.md` for query patterns.

---

## Step 4 — Signal handling for span flushing

Without signal handling, interrupted processes lose all open spans — they never flush to Axiom. Register handlers for SIGINT, SIGTERM, and atexit:

```python
import signal
import atexit

_active_spans = []  # Stack of open spans for cleanup


def _cleanup_spans(status_msg="interrupted"):
    """End all active spans with appropriate status before exit."""
    while _active_spans:
        span = _active_spans.pop()
        if span.is_recording():
            span.set_status(StatusCode.ERROR, status_msg)
            span.end()


def _signal_handler(signum, frame):
    """Handle SIGINT/SIGTERM by flushing spans and exiting."""
    sig_name = signal.Signals(signum).name
    _cleanup_spans(f"interrupted by {sig_name}")
    provider = trace.get_tracer_provider()
    if hasattr(provider, "force_flush"):
        try:
            provider.force_flush(timeout_millis=5000)
        except Exception:
            pass
    sys.exit(128 + signum)


signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)
atexit.register(lambda: _cleanup_spans("process exiting"))
```

### Usage pattern

Push spans onto `_active_spans` when opening, pop when closing:

```python
with tracer.start_as_current_span("my.span", attributes={...}) as span:
    _active_spans.append(span)
    try:
        # ... do work ...
        span.set_status(StatusCode.OK)
        _active_spans.pop()
    except Exception as e:
        span.set_status(StatusCode.ERROR, str(e))
        span.record_exception(e)
        _active_spans.pop()
        raise
```

---

## Step 5 — CC subprocess resource attributes

If the application spawns Claude Code subprocesses (via Antkeeper or directly), set `OTEL_RESOURCE_ATTRIBUTES` as an env var so CC inherits them:

```python
os.environ["OTEL_SERVICE_NAME"] = app_name
attrs = f"build.id={build_id},build.app_name={app_name}"
existing = os.environ.get("OTEL_RESOURCE_ATTRIBUTES", "")
if existing:
    attrs = f"{existing},{attrs}"
os.environ["OTEL_RESOURCE_ATTRIBUTES"] = attrs
```

CC's own exporter reads these env vars. CC spans will have `resource.build.id` as a flattened top-level column in Axiom (CC uses a non-standard exporter that Axiom treats differently from the Python SDK).

---

## Verification Checklist

After completing all steps, verify each item:

- [ ] Python OTEL dependencies installed
- [ ] Bash wrapper sets exporter env vars and launches with `with-otel` (no `opentelemetry-instrument`)
- [ ] TracerProvider configured programmatically with `Resource()` (not `Resource.create()`)
- [ ] Signal handlers registered for SIGINT, SIGTERM, atexit
- [ ] Active spans tracked in `_active_spans` stack for cleanup
- [ ] `OTEL_RESOURCE_ATTRIBUTES` set for CC subprocesses
- [ ] Test span visible in Axiom after a test run
- [ ] Resource attributes appear in `resource.custom` (Python spans) and `resource.build.id` (CC spans)
