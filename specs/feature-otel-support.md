# feature: OpenTelemetry tracing for workflows and LLM calls

- Every workflow step and LLM call emits an OTel span with structured attributes (tokens, cost, session_id).
- Spans correlate with Claude Code's own OTel output in Axiom via run_id and session_id.
- File logging unchanged; OTel is additive, activated by standard OTEL_* env vars.

## Solution Design

### External Interface Change

**No new CLI commands or API endpoints.** Tracing is activated entirely via standard OpenTelemetry environment variables. When `OTEL_EXPORTER_OTLP_ENDPOINT` (and optionally `OTEL_EXPORTER_OTLP_HEADERS`) is set, spans are exported. When unset, the no-op tracer is used and there is zero overhead.

The OTel packages are core dependencies, not optional extras. See `app_docs/standards.md` for the rationale.

**Axiom configuration example (CLI or server):**

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT="https://api.axiom.co"
export OTEL_EXPORTER_OTLP_HEADERS="Authorization=Bearer api_xxx,X-Axiom-Dataset=antkeeper"
export OTEL_SERVICE_NAME="antkeeper"
antkeeper run --model sonnet sdlc prompts/add-auth.md
```

No channel-specific changes. All channels (CLI, API, Slack) benefit automatically because tracing is in the core execution path.

### Architectural Schema Changes

```yaml
modules:
  antkeeper.tracing:
    description: >
      Thin wrapper over opentelemetry.trace. Conditional import — if
      opentelemetry-api is not installed, returns a no-op tracer.
      Does NOT configure TracerProvider. Provider setup is the
      deployer's responsibility (via OTEL_* env vars or programmatic
      setup in entry points).

functions:
  get_tracer:
    module: antkeeper.tracing
    params: []
    returns: "opentelemetry.trace.Tracer"
    notes: >
      Module-level lazy singleton. Calls trace.get_tracer("antkeeper").

dependencies:
  core:
    - opentelemetry-api
    - opentelemetry-sdk
    - opentelemetry-exporter-otlp-proto-http
```

### Instrumentation Points

**1. `Runner.run()` — root span**

Span name: `antkeeper.run`
Attributes: `run_id`, `workflow_name`, `channel.type`
On exception: record exception on span, set span status to ERROR, re-raise.

**2. `run_workflow()` — per-step child spans**

Span name: `antkeeper.workflow.step`
Attributes: `run_id`, `workflow_name`, `step_name`, `step_index`, `step_total`
On exception: record exception on span, set span status to ERROR, re-raise.

No separate parent span for `run_workflow` itself — `Runner.run()` already provides the parent. `run_workflow` is called inside the handler invocation which is inside the `Runner.run()` span.

**3. `ClaudeCodeAgent.prompt()` — per-LLM-call child spans**

Span name: `antkeeper.llm.call`
Attributes (set after successful call): `session_id`, `duration_ms`, `input_tokens`, `output_tokens`, `total_cost_usd`, `model`
Attributes (set before call): `prompt_length`
On exception: record exception on span, set span status to ERROR, re-raise.

### Span Hierarchy (typical workflow)

```
antkeeper.run (run_id, workflow_name, channel.type)
  └─ antkeeper.workflow.step (step_name="specify", step_index=0)
  │    └─ antkeeper.llm.call (session_id, cost, tokens)
  │    └─ antkeeper.llm.call (extraction call to haiku)
  └─ antkeeper.workflow.step (step_name="branch", step_index=1)
  └─ antkeeper.workflow.step (step_name="implement", step_index=2)
       └─ antkeeper.llm.call (session_id, cost, tokens)
```

## Acceptance Criteria

1. When `OTEL_EXPORTER_OTLP_ENDPOINT` is set, running a workflow produces spans visible in the configured backend.
2. When no exporter endpoint is configured, the no-op tracer is used and workflows execute normally.
4. Each `Runner.run()` invocation produces exactly one root span with `run_id`, `workflow_name`, and `channel.type` attributes.
5. Each step in `run_workflow` produces a child span with `step_name`, `step_index`, `step_total`, `run_id`, and `workflow_name` attributes.
6. Each `ClaudeCodeAgent.prompt()` call produces a span with `session_id`, `duration_ms`, `input_tokens`, `output_tokens`, `total_cost_usd`, and `model` attributes (values may be None if absent from Claude's envelope).
7. When a step or LLM call raises an exception, the corresponding span records the exception and has ERROR status. The exception still propagates normally.
8. Existing file-based logging is unmodified — all current log output continues at the same levels and destinations.
9. The `antkeeper.tracing` module does NOT configure a TracerProvider. It only calls `trace.get_tracer("antkeeper")`.
10. No new keys are added to State. Tracing is purely a side-effect and does not touch the `(Runner, State) -> State` contract.
11. All existing tests continue to pass.

### Validation Commands

```bash
uv run ruff check src/ tests/
uv run ty check src/
uv run pytest tests/ -v
```

IMPORTANT: All checks must pass with zero errors and zero warnings. Investigate and fix any failures — do not explain them away.

## Resources

### Documentation

- **app_docs/instrumentation.md** — Describes the current logging, state persistence, and progress reporting patterns. Essential for understanding where tracing hooks into the existing lifecycle (Runner.run, run_workflow step loop, ClaudeCodeAgent telemetry extraction).
- **app_docs/reference.md** — Project structure and core concept details. Needed to understand the module layout and where the new `tracing.py` fits.
- **app_docs/testing_policy.md** — Test fixture patterns and conventions. Needed for writing OTel tests that follow existing patterns.
- **app_docs/releasing.md** — Dependency model and packaging. Needed to correctly add the OTel packages as core dependencies.
- **app_docs/standards.md** — Engineering standards. Documents why OTel packages are core deps (not optional) and why framework performance is not a concern.

### Experts

- **design-expert** — Invoke when deciding whether a tracing pattern fits Antkeeper's architecture (e.g. "should this live in Runner or in a standalone module?", "does this violate the reducer pattern?").
- **otel-expert** — Invoke for OpenTelemetry-specific questions: correct SDK usage, TracerProvider configuration patterns, OTLP exporter setup, Axiom header format, span attribute naming conventions, context propagation behaviour in synchronous Python code.

## Notes

- **No `@traced` decorator or tracing middleware.** Instrumentation is explicit `with tracer.start_as_current_span(...)` at three specific call sites. This keeps tracing visible and avoids magic.
- **No `TracingConfig` or configuration abstraction.** OTel's own env-var-based configuration is sufficient. Do not invent a wrapper.
- **Context propagation is automatic.** Because `run_workflow` calls steps synchronously and steps call `ClaudeCodeAgent.prompt()` synchronously, Python's `contextvars`-based OTel propagation creates correct parent-child relationships with no extra wiring.
- **No-op fallback.** When no exporter endpoint is configured, OTel's built-in no-op tracer handles this automatically. No custom fallback objects needed.
- **Span attribute naming.** Use flat, dot-free attribute names (`run_id`, `session_id`, `input_tokens`) rather than OTel semantic convention namespaces. These are domain-specific attributes, not generic HTTP/DB spans.
