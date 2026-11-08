# Workflow schema v1: structural validation

Session 2 implements loading and local structural validation through
`forgeflow.workflow.load_workflow(path)` and `parse_workflow(content: bytes)`.
Neither API executes a workflow. The CLI still exposes only help and version.

## Input and safety limits

- UTF-8, optionally with a UTF-8 BOM; at most 1 MiB, measured in bytes.
- Exactly one document with a mapping root; all mapping keys are strings.
- Unique keys at every mapping level, including escaped/quoted equivalents.
- No anchors, aliases, merge keys, explicit tags, or tag directives.
- At most 32 nested collections, counting the root as depth one.
- At most 20,000 YAML parser events, bounding wide documents independently of size.
- JSON-compatible strings, lowercase `true`/`false`, `null`, integers, and finite
  decimal/exponent numbers. An empty scalar is also null. Quote YAML-specific
  forms such as `yes`, `off`, `~`, `012`, hexadecimal numbers, and timestamps
  to use them as strings; their implicit YAML scalar types are rejected.
- Non-finite numbers and integers longer than 4,096 characters are rejected,
  independently of Python's configurable integer-conversion limit.

The loader checks events before composing a node tree and manually converts only
approved node types. It never calls YAML object constructors. File reads request
at most the byte limit plus one; errors omit the file path and source text.

## Root and shared configuration

Required fields are `schema_version: 1`, `name`, and `steps`. Version must be an
integer, not a boolean or quoted number. Names match `[a-z][a-z0-9_-]{0,63}`.
There must be 1–100 steps with unique IDs. Unknown fields are rejected everywhere.

| Field | Default | Accepted values |
|---|---|---|
| `execution.concurrency` | 4 | Integer 1–16 |
| `execution.timeout_seconds` | 300 | Number 1–3,600 |
| `defaults.attempt_timeout_seconds` | 30 | Number greater than 0, at most 300 |
| Step `attempt_timeout_seconds` | Inherit defaults | Number greater than 0, at most 300 |
| HTTP `retry.max_attempts` | 1 | Integer 1–5 |

Numbers are not coerced from strings or booleans. A step timeout omitted in YAML
is represented as `None` in the model for future default resolution; explicitly
setting it to null is invalid. Execution settings are validated but have no runtime
effect until execution is implemented.

Every step requires `id` and `type`. Step IDs, output names, and `needs` entries
match `[a-z][a-z0-9_]{0,63}`. `needs` defaults to an empty list, permits at most
100 entries, and cannot contain duplicate entries. This session does not check
whether dependencies exist, are self-references, or form cycles.

## Built-in step definitions

### Value

`type: value` requires `values`, a mapping of 1–100 output names to JSON-compatible
values. Values may contain nested lists and objects with string keys.

### Assertion

`type: assert` requires `left`, `op: eq`, and `right`. Each operand contains
exactly one field:

- `literal`: a JSON-compatible value, including null, lists, and objects.
- `ref`: a string in the form `step_id.outputs.output_name`.

Reference syntax is checked now. Producer existence, output existence, and
explicit dependency membership will be validated in Session 3.

### HTTP

`type: http` requires `request.method` (`GET` or `HEAD`) and `request.url`.
Request bodies and write methods are forbidden. URLs must be absolute HTTP(S)
URLs with no credentials, embedded query string, fragment, whitespace, or controls.
Localhost, IP addresses, and international hostnames are supported; validation
does not resolve DNS or promise an endpoint exists or is safe to contact.

Optional fields:

- `expect_status`: 1–500 integer status codes in 100–599; defaults to 200–299.
- `retry`: the retry policy above; other retry controls are not part of schema v1.
- `capture`: up to 100 output names mapped to JSON pointers. Pointers must start
  with `/` and use valid `~0`/`~1` escaping, with at most 1,024 characters. Empty
  root pointers and the reserved output name `status_code` are forbidden.
- HEAD requests must have no body captures. An empty `capture` mapping is allowed.
- `request.query`: up to 100 keys mapped to literal or reference operands.
  Literals must be non-null scalar values. Keys are 1–256 characters, with no
  whitespace/controls; common credential names are forbidden.
- `request.headers`: up to 100 case-insensitively unique HTTP token names, each
  at most 128 characters. Values are either `{literal: "text"}` or
  `{secret: ENVIRONMENT_NAME, prefix: "optional prefix"}`. Header literals are
  at most 8,192 characters and prefixes at most 128; both use printable ASCII.
  Secret references are names only and are never resolved during loading.

Transport-managed headers, cookies, and proxy authorization are forbidden.
Known credential headers require secret operands. Common-name checks are not a
general secret detector; keep all credentials out of workflow literals.

Examples: [values](../examples/values.yaml), [API health](../examples/api-health.yaml),
and [intentionally invalid workflows](../examples/invalid/).

## Diagnostics

Catch `WorkflowLoadError` at the loading boundary. Its `diagnostics` tuple has
stable codes, a safe `message`, and a machine-readable `location` tuple. Use
`to_dict()` for JSON-compatible dictionaries. YAML syntax and node errors may
also include one-based line/column positions; they never include source snippets.

Locations retain known schema fields and numeric list indexes, for example
`["steps", 0, "request", "headers", "<key>", "literal"]`. User-defined keys are
replaced by `<key>` to prevent credentials or private header names leaking through
error paths. Up to 50 distinct diagnostics are returned, followed by
`DIAGNOSTICS_TRUNCATED` when more were omitted.

Only the loading boundary provides this sanitized error contract. Calling
Pydantic's model APIs directly is intended for internal typed code, not for
rendering untrusted validation errors. Do not log loaded workflow objects,
raw Pydantic `.errors()`, exception locals, or parser internals.

No graph analysis, request execution, database, recorder, replay, or web interface
is implemented in this session.
