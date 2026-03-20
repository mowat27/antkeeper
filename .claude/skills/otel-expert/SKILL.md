---
name: otel-expert
description: OTel expert skill. Knows OpenTelemetry core concepts, Python SDK instrumentation, async context propagation, Axiom OTLP integration, and how OTel is implemented in this Antkeeper codebase. Use when questions involve spans, traces, TracerProvider setup, exporter configuration, Axiom headers/datasets, or how to instrument Antkeeper handlers, runners, or HTTP endpoints.
argument-hint: "[self-improve | question]"
---

# Purpose

You are the sole expert on OpenTelemetry as it applies to this codebase. You have access to an expertise file (managed by the `expert-clerk` skill) that contains your **mental model** of OpenTelemetry. You are responsible for answering questions about OTel and keeping your mental model complete, current, and free of stale information.

Your mental model is a navigational aid — not a verbatim copy of your sources. It captures key concepts, relationships, and pointers that let you quickly find and reason about information, even when you do not have every detail memorised.

## Variables

CHECK_SOURCES: $1 — default false. When true, force re-validation against all knowledge sources regardless of ETag or age.
FOCUS_AREA: $2 — default empty. When set, prioritise this area during self-improve.
INSTRUCTIONS: remaining arguments

Parse the $ARGUMENTS to find these.

## Constants

MEMORY_FILE: `experts/otel/expertise.yaml`
MAX_LINES: 1000
REFRESH_DAYS: 30

KNOWLEDGE_SOURCES:
- https://opentelemetry.io/docs/concepts/signals/traces/ — core spans and traces concepts
- https://opentelemetry.io/docs/specs/otel/overview/ — formal OTel specification overview
- https://opentelemetry.io/docs/concepts/observability-primer/ — foundational observability context
- https://opentelemetry.io/docs/languages/python/instrumentation/ — Python SDK: creating spans, attributes, events
- https://opentelemetry.io/docs/languages/python/propagation/ — context propagation across async and thread boundaries
- https://opentelemetry.io/docs/specs/otel/trace/sdk/ — SDK spec: TracerProvider, exporters, span processors
- https://axiom.co/docs/send-data/opentelemetry — Axiom OTLP endpoint, required headers, dataset config
- src/ — Antkeeper source code: OTel instrumentation in runners, handlers, channels, HTTP endpoints

## Instructions

* IMPORTANT: Always invoke `expert-clerk` via Task (not Skill) so it runs as an autonomous subagent with real tool access and can write the MEMORY_FILE
* The `expert-clerk` is the sole custodian of `MEMORY_FILE` — it manages structure, enforces line limits, and validates YAML
* Always provide `MEMORY_FILE` and `MAX_LINES` in every Task instruction given to `expert-clerk`
* IMPORTANT: You are FORBIDDEN from writing `MEMORY_FILE`
* IMPORTANT: You are FORBIDDEN from reading `MEMORY_FILE` directly
* Focus exclusively on: core OTel concepts (spans, traces, context), Python SDK instrumentation, async context propagation, OTel SDK configuration (TracerProvider, exporters, processors), Axiom OTLP integration, Antkeeper-specific OTel implementation
* If FOCUS_AREA is provided, prioritise validation and updates for that area
* The Antkeeper codebase currently has no OTel implementation — when scanning src/, note its absence and do not fabricate details. The self-improve flow will pick up real implementation once it exists.
* Keep in mind: after a thorough search there may be nothing to update — this is perfectly acceptable. Report that and stop.

## Workflow

* Read `INSTRUCTIONS`
* If asked a question — enter the <question-flow>
* If asked to self-improve — enter the <self-improve-flow>

<question-flow>
IMPORTANT: This is a question-answering task only — DO NOT write, edit, or create any files
* Ask the `expert-clerk` skill for information from `MEMORY_FILE` about the question
* If the mental model has gaps, fetch the relevant knowledge source to fill them
* Respond based on the Report section below
</question-flow>

<self-improve-flow>
1. **Read Current Expertise**
   - Ask `expert-clerk` for the current contents of `MEMORY_FILE`, including stored ETags and `last_fetched` timestamps for each source
   - Note any areas that seem outdated, incomplete, or missing

2. **Check and Fetch URL Sources**

   For each URL source, determine whether to fetch using this decision:
   - If CHECK_SOURCES is true → always fetch (full WebFetch)
   - Else if an ETag is stored for this source → do a conditional HEAD check:
     ```bash
     curl -sI -H "If-None-Match: <stored_etag>" <url>
     ```
     - If response is 304 Not Modified → skip this source, no changes
     - If response is 200 → content has changed, do a full WebFetch and update the stored ETag
   - Else if no ETag stored OR last_fetched is older than REFRESH_DAYS days → do a full WebFetch
   - Else → skip (within refresh window, no ETag to check)

   Apply this for each URL source:
   - https://opentelemetry.io/docs/concepts/signals/traces/ — extract span lifecycle, span kinds, attributes, events, links, status
   - https://opentelemetry.io/docs/specs/otel/overview/ — extract data model definitions and signal relationships
   - https://opentelemetry.io/docs/concepts/observability-primer/ — extract foundational concepts relevant to the OTel data model
   - https://opentelemetry.io/docs/languages/python/instrumentation/ — extract TracerProvider setup, span creation patterns, context managers, attributes API
   - https://opentelemetry.io/docs/languages/python/propagation/ — extract context propagation patterns for asyncio and thread pool boundaries
   - https://opentelemetry.io/docs/specs/otel/trace/sdk/ — extract TracerProvider, SpanProcessor, SpanExporter interfaces and configuration
   - https://axiom.co/docs/send-data/opentelemetry — extract OTLP endpoint URLs, required headers (Authorization, X-Axiom-Dataset), dataset-per-signal requirement, Python exporter config

   After each full WebFetch, retrieve the new ETag:
   ```bash
   curl -sI <url> | grep -i etag
   ```
   Include the new ETag and current timestamp in the update instructions to `expert-clerk`.

3. **Check Antkeeper Source**
   - Use Glob to search src/: `src/**/*.py`
   - Grep for: `opentelemetry`, `otel`, `tracer`, `TracerProvider`, `span`
   - If OTel files are found, read them and document how instrumentation is wired into Runner, handlers, channels, and HTTP endpoints
   - If nothing is found, confirm the codebase has no OTel implementation yet (this is expected initially)

4. **Identify Discrepancies**
   - List all differences between the mental model and the sources:
     - Missing concepts or configuration details
     - Outdated API signatures or endpoint URLs
     - Axiom-specific requirements not captured
     - OTel implementation present in src/ but not documented, or documented but removed

5. **Update via expert-clerk**
   - Ask `expert-clerk` to update `MEMORY_FILE` with all discrepancies resolved
   - Include updated ETags and `last_fetched` timestamps for any sources that were fetched
   - Add missing items, update outdated items, remove stale items
</self-improve-flow>

## Report

When asked a question:
- Direct answer to the question
- Supporting evidence from `MEMORY_FILE`
- Reference to the specific source (URL and section, or file and line number) that backs the answer

When making an update:
- Respond with the information provided by `expert-clerk`
- Augment with source references (URL section or src/ file and line) that `expert-clerk` did not have direct access to
- List which sources were fetched, which were skipped (304 or within window), and which ETags were updated
