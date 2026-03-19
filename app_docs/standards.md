# Engineering Standards

Technical standards that guide framework decisions. These are not aspirational — they reflect the actual operating constraints and should be applied when evaluating trade-offs.

## Dependency Philosophy

Antkeeper is not a zero-dependency micro-library. It is a workflow engine that orchestrates LLM calls, manages state, serves HTTP endpoints, and posts to Slack. Dependencies that serve the framework's purpose are added as core dependencies without hesitation.

Do not split dependencies into optional extras to "minimise install footprint." The framework runs on developer VMs and CI machines, not size-constrained environments. The cognitive cost of optional import paths, silent no-ops, and multiple install configurations outweighs any packaging benefit.

Add a dependency when it does the job. Remove it when it no longer does.

## Performance

Antkeeper's workload is dominated by LLM calls that take seconds to minutes each. Framework overhead — import time, tracing instrumentation, JSON serialisation, subprocess setup — is negligible by comparison and should never be a factor in design decisions.

Do not optimise framework internals for speed. Do not avoid a dependency because it "might be slow." Do not add caching, pooling, or async where the synchronous path is already fast enough. If a profiler shows a real bottleneck that is not an LLM call, fix it then.

## No Singletons

Do not introduce singleton patterns, module-level caches, or lazy-init global instances. Use the idiomatic approach provided by the library or framework instead. For example, OpenTelemetry's `trace.get_tracer("antkeeper")` already caches internally — wrapping it in a module-level singleton adds complexity, couples modules to import-time state, and makes testing harder (every test must monkeypatch the singleton in every module that imported it).

The motivation for singletons is almost always a premature performance concern ("avoid calling this twice"). That concern does not apply here — see Performance above. Do the simplest thing that works. If a profiler later shows a real bottleneck, optimise then.
