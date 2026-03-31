# OTel Concepts Reference

Core OpenTelemetry concepts and Python SDK internals. Read this when you need to understand what something is before applying the standards in `coding-standards.md`.

---

## Signals

OpenTelemetry defines three signal types: **traces**, **metrics**, and **logs**. This codebase uses traces only.

---

## Traces and Spans

A **trace** is a directed acyclic graph of spans sharing the same `trace_id`. A **span** is the building block — a unit of work with start/end timestamps.

### Span structure

| Field | Description |
|-------|-------------|
| `name` | Operation name |
| `trace_id` | Shared by all spans in a trace |
| `span_id` | Unique to this span |
| `parent_span_id` | Empty for root spans |
| `start_timestamp` / `end_timestamp` | Wall-clock times |
| `attributes` | Key-value metadata (string, bool, number, array values) |
| `events` | Point-in-time occurrences with timestamps |
| `links` | Optional associations to causally related spans across traces |
| `status` | `Unset` (default/success), `Ok` (explicit success), `Error` |

### Span kinds

| Kind | Use |
|------|-----|
| `INTERNAL` | Within a single process |
| `SERVER` | Incoming remote call |
| `CLIENT` | Outgoing remote call |
| `PRODUCER` | Async job creation |
| `CONSUMER` | Async job processing |

### Events vs attributes

Use **events** when timing within a span matters. Use **attributes** for data that describes the span as a whole.

---

## Context propagation

Context (trace identity + baggage) is carried across boundaries via **propagators**.

- **Default:** W3C Trace Context HTTP headers (`traceparent`, `tracestate`)
- **Inject:** `opentelemetry.propagate.inject(carrier)` — writes context into a dict/headers
- **Extract:** `opentelemetry.propagate.extract(carrier)` — reads context from a dict/headers

Within a single Python process, context propagates automatically via `contextvars` — no manual inject/extract needed for synchronous or async calls in the same process.

For **subprocess boundaries**, inject into the environment dict before spawning. The subprocess reads it via `OTEL_*` env vars if it uses `opentelemetry-instrument`, or manually via `extract`.

---

## Python SDK

### API vs SDK

- **API** (`opentelemetry-api`) — interfaces for instrumentation. Libraries use only this.
- **SDK** (`opentelemetry-sdk`) — implementation configured by application owners.

### Minimal setup

```python
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

provider = TracerProvider(resource=resource)
provider.add_span_processor(BatchSpanProcessor(exporter))
trace.set_tracer_provider(provider)
tracer = trace.get_tracer("my-app")
```

### Creating spans

```python
# Context manager (preferred)
with tracer.start_as_current_span("my.span") as span:
    span.set_attribute("key", "value")

# Nested — inner span becomes a child automatically
with tracer.start_as_current_span("outer") as outer:
    with tracer.start_as_current_span("inner") as inner:
        ...
```

### Setting status and recording exceptions

```python
from opentelemetry.trace import StatusCode

span.set_status(StatusCode.ERROR, "something failed")
span.record_exception(exc)
```

---

## SDK internals

### TracerProvider

Owns span processors, sampler, ID generators, and span limits. Creating a `Tracer` via `get_tracer()` returns a view onto the provider's configuration.

Key methods: `force_flush(timeout_millis)`, `shutdown()`.

### SpanProcessor

| Processor | Behaviour |
|-----------|-----------|
| `SimpleSpanProcessor` | Exports immediately on `span.end()` — use in tests |
| `BatchSpanProcessor` | Batches by queue size or scheduled delay — use in production |

`on_start` is called synchronously at span start (read/write access). `on_end` is called after the span ends (read-only).

### SpanExporter

`export(batch)` sends spans and returns `SUCCESS` or `FAILURE`. `force_flush()` blocks until pending spans are flushed. Must not block indefinitely — retry logic is the processor's responsibility.

### Samplers

| Sampler | Behaviour |
|---------|-----------|
| `AlwaysOn` | Record all spans |
| `AlwaysOff` | Drop all spans |
| `TraceIdRatioBased` | Sample by ratio |
| `ParentBased` | Delegate to parent's sampling decision |
