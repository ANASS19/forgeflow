# ForgeFlow roadmap

ForgeFlow is an independently maintained, pre-alpha project. Items below describe
engineering work, not release-date promises. The current implementation is useful
for learning, testing, and debugging small pure-step workflows locally.

## Completed checkpoints

- Installable Python 3.12 package, Typer CLI, locked uv dependencies, and Apache-2.0 licensing.
- Bounded YAML loading, strict schema v1, safe diagnostics, and hostile-input tests.
- Explicit DAG construction, real cycle paths, and reference/output validation.
- CLI `validate` and static `doctor`, including optional secret-presence checks.
- Async value/assert execution with concurrency limits and dependency gating.
- Failure propagation, skipped-dependant causes, deadlines, and cancellation.
- SQLite history/inspection, atomic attempt events, and privacy-filtered value recording.
- OS writer exclusion, abandoned-run recovery, fresh linked runs, and explicit pruning.
- Offline success/failure demonstration and cross-platform CI configuration.

## Next: safe HTTP execution

- Implement GET/HEAD with HTTPX, isolated cookies, TLS verification, and no redirects by default.
- Enforce streamed byte/depth limits and strict JSON capture semantics.
- Resolve explicit secret references only at execution time; omit request data from persistence.
- Record normalized outcomes without raw URLs, headers, query strings, or exception text.
- Verify behavior using mock transports and a loopback API, never public service credentials.

## Bounded retries and recovery hardening

- Add observable retry decisions, exponential jitter, and bounded `Retry-After` handling.
- Release concurrency slots during retry waits; respect the workflow deadline.
- Classify transient versus permanent failures conservatively.
- Add forced-termination, database-failure, migration, and cancellation-race tests.
- Preserve unknown external outcomes honestly; do not claim exactly-once execution.

## Flight Recorder and offline replay

- Complete and version the recording contract and required-value availability rules.
- Replay supported recorded executions without network or environment-secret capability.
- Reevaluate deterministic pure steps and report divergence explicitly.
- Fail clearly for missing, redacted, incompatible, or incomplete evidence.
- Test with networking disabled; never fall back to a live request.

## Developer experience and release readiness

- Add execution-time Doctor explanations grounded in stored evidence.
- Improve event timelines and diagnosis without exposing sensitive values.
- Expand privacy canaries and storage-limit fault injection.
- Document compatibility, retention, and migration guarantees before a stable release.
- Validate a complete local API failure/diagnosis/replay journey before advertising it.

Distributed workers, scheduling services, arbitrary code actions, and a web UI
are outside the initial MVP. General plugin infrastructure is deferred until a
demonstrated use case justifies its security and replay complexity.
