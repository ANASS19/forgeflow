# CLI reference: current checkpoint

All commands support `--help`. `--json` emits one JSON document on stdout with
`output_version: 1`. Human run progress goes to stderr. Input values, HTTP request
details, and captured values are not displayed in errors or default inspection.

| Command | Behavior |
|---|---|
| `forgeflow validate FILE` | Validate YAML, schema, DAG, and output-reference contracts |
| `forgeflow doctor FILE [--check-env]` | Static diagnostics; optional secret-presence checks |
| `forgeflow run FILE [--parent RUN_ID]` | Execute a fresh value/assert/HTTP GET/HEAD workflow |
| `forgeflow history` | List up to 100 latest local runs |
| `forgeflow inspect RUN_ID` | Inspect states, attempts, causes, events, and value availability |
| `forgeflow recover` | Mark abandoned runs and unfinished work interrupted |
| `forgeflow history prune --older-than DAYS` | Delete terminal runs older than a positive age |

Execution/history/recovery commands accept `--data-dir DIRECTORY`. For pruning,
put it after `prune`. The `FORGEFLOW_DATA_DIR` environment variable is an alternative.
Default locations are `%LOCALAPPDATA%/ForgeFlow` on Windows,
`$XDG_STATE_HOME/forgeflow` (or `~/.local/state/forgeflow`) on Linux, and
`~/Library/Application Support/ForgeFlow` on macOS.

Validation and static Doctor do not create storage. Empty history does not create
a directory. Mutating commands initialize storage lazily. Use a local disk;
network shares and synchronized database directories are not supported.

`--parent` links provenance and repeats every step using the supplied file. It
does not reuse earlier outputs. Recovery does not resume execution. A live writer
prevents another writer or recovery command from acquiring the same database.

Exit codes: 0 success; 1 workflow failure; 2 invalid workflow/arguments or unavailable
action; 3 storage/lock/infrastructure failure; 124 workflow deadline; 130 cancellation.
An exhausted attempt timeout fails its step and therefore the workflow with code 1.

HTTP executes one attempt by default. Set `retry.max_attempts` from 1 to 5 to
retry eligible transient failures. Each attempt and chosen delay appears in
inspection history. A delay that cannot fit the remaining workflow budget is
not scheduled; the final attempt outcome is retained. There is no `replay`
command yet. `doctor` currently analyzes workflow files, not prior executions.
