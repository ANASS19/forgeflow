# Architecture and failure semantics

ForgeFlow is a typed Python modular monolith. The current execution engine runs
only value and assertion steps; HTTP is a validated schema, not a live action.

## Boundaries

- `workflow/`: bounded YAML loading, strict models, explicit edges, references, and cycle paths.
- `engine/`: readiness, bounded async tasks, operand resolution, and pure-step evaluation.
- `storage/`: SQLAlchemy mappings, SQLite transactions, immutable Alembic migration, and OS lock.
- `recorder/privacy.py`: retained-value eligibility and request-free recording-plan snapshots.
- `cli.py`, `runtime_cli.py`, and `doctor.py`: commands, safe output, and static diagnosis.

The scheduler awaits a committed attempt-start record before dispatch. Attempt
completion, captured values, and its event commit in one transaction before a
dependant is released. A dedicated storage worker serializes sessions off the
asyncio event loop. Independent branches can run concurrently.

Kahn's algorithm builds a stable topological order, breaking ties by declaration
position. A bounded DFS reports an actual cycle path using numeric step locations.
References require a declared producer output and an explicit `needs` edge.

## State and failure handling

Runs start pending conceptually, persist as running, and terminate as succeeded,
failed, timed out, cancelled, or interrupted. Steps pass through readiness and
running; failed dependencies make downstream steps skipped with causal IDs.
Independent branches continue after ordinary failure. Attempts have independent
terminal outcomes. Retry-wait state exists for future retry support; no retries
are performed by this checkpoint.

One OS advisory lock owns mutating commands per database. WAL permits readers
alongside that writer. Foreign keys, FULL synchronization, a bounded busy timeout,
and explicit Python 3.12 SQLite transactions are enabled. Existing unknown schema
revisions are rejected without replacing the database. New databases receive
Alembic revision `0001`; upgrades to future revisions are not yet implemented.

Loss of the writer releases its OS lock. A later `recover` command marks abandoned
nonterminal records interrupted and dispatches no work. Starting another run
requires that recovery first. A linked run starts fresh. Pruning leaves parent IDs
as historical provenance references even when the parent itself has been pruned.

Storage failures stop scheduling and may leave a running record that requires
recovery. Cancellation cleanup and SQLite durability depend on the process,
operating system, and filesystem; there is no power-loss or exactly-once promise.

## Recording and privacy

Persisted execution evidence includes normalized states, attempt duration, causal
IDs, events, output availability, and approved values. Sensitive-key detection
and explicitly supplied known-secret strings can make an entire output unavailable
for recording. No raw HTTP request configuration is included in plan snapshots.

Recordings are plaintext. Filtering is heuristic, not a guarantee that arbitrary
private input is recognized. Displayed inspection includes availability rather
than the actual captured values. Per-step captured values are bounded to 256 KiB;
recording payloads are bounded to 16 MiB and 10,000 events per run. Exceeding a
storage budget fails persistence rather than silently disabling the recorder.

Flight Recorder semantics, replay completeness checks, and offline replay are
future work. The stored plan is a foundation for them, not a replay guarantee.
