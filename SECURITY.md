# Security and privacy

ForgeFlow is pre-alpha software. Do not use it as a sandbox or put secrets,
personal information, confidential datasets, or proprietary code in public
workflows, issue reports, test fixtures, or execution histories.

The current checkpoint executes built-in value/assert steps only. YAML aliases,
anchors, merges, explicit tags, object construction, and arbitrary workflow code
are rejected. Parsing has size, depth, event, and numeric-conversion budgets.
HTTP execution and offline replay are not available yet.

The intended HTTP MVP will use explicit secret references and field-level capture,
but executing a workflow will remain a trusted-user action. The future replay
implementation must never fall back to live network activity.

Local SQLite data is not encrypted. Privacy filtering cannot detect every secret
or private field. Use synthetic data, restrict operating-system access to the data
directory, and never attach databases or raw recordings to a public issue. History
pruning is not a secure-erasure guarantee. Do not use network/synchronized folders
for the database.

## Reporting

Do not post credentials, private workflows, or exploit payloads publicly. Use
GitHub's private vulnerability reporting option if it is available on the repository.
Otherwise, open a minimal issue asking for a private reporting channel without
including sensitive details. Ordinary non-sensitive bugs can use the bug template.

Only the current main-branch development checkpoint is being maintained; there
are no stable releases or security-support guarantees yet.
