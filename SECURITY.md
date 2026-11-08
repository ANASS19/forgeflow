# Security and privacy

ForgeFlow is pre-alpha software. Do not use it as a sandbox or put secrets,
personal information, confidential datasets, or proprietary code in public
workflows, issue reports, test fixtures, or execution histories.

The current checkpoint executes built-in value/assert steps and HTTP GET/HEAD. YAML aliases,
anchors, merges, explicit tags, object construction, and arbitrary workflow code
are rejected. Parsing has size, depth, event, and numeric-conversion budgets.
Offline replay is not available yet.

HTTP uses explicit secret references, field-level capture, TLS verification, and
isolated clients without redirects or environment proxies. Executing a workflow
is a trusted-user action and can contact local services. GET/HEAD intent does not
guarantee a remote server has no side effects. No external exactly-once guarantee exists.
Known-secret captures are excluded from storage; unknown private fields still require care.
The future replay
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
