"""Initial local execution schema. Do not import mutable application metadata."""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    statements = [
        "CREATE TABLE runs (id TEXT PRIMARY KEY, name TEXT NOT NULL, parent_id TEXT, "
        "mode TEXT NOT NULL, state TEXT NOT NULL, created TEXT NOT NULL, ended TEXT, "
        "plan TEXT NOT NULL, event_count INTEGER NOT NULL, recorded_bytes INTEGER NOT NULL)",
        "CREATE INDEX ix_runs_created ON runs(created)",
        "CREATE TABLE step_runs (run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE, "
        "step_id TEXT NOT NULL, position INTEGER NOT NULL, kind TEXT NOT NULL, "
        "state TEXT NOT NULL, "
        "causes TEXT NOT NULL, PRIMARY KEY (run_id, step_id))",
        "CREATE TABLE attempts (id INTEGER PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id) "
        "ON DELETE CASCADE, step_id TEXT NOT NULL, number INTEGER NOT NULL, state TEXT NOT NULL, "
        "code TEXT, status_code INTEGER, duration REAL, retryable BOOLEAN NOT NULL, "
        "retry_delay REAL, "
        "UNIQUE(run_id, step_id, number))",
        "CREATE INDEX ix_attempts_run_id ON attempts(run_id)",
        "CREATE TABLE recorded_values (run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE, "
        "step_id TEXT NOT NULL, name TEXT NOT NULL, availability TEXT NOT NULL, value TEXT, "
        "PRIMARY KEY (run_id, step_id, name))",
        "CREATE TABLE events (run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE, "
        "sequence INTEGER NOT NULL, kind TEXT NOT NULL, step_id TEXT, attempt INTEGER, "
        "timestamp TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY (run_id, sequence))",
    ]
    for statement in statements:
        op.execute(statement)


def downgrade() -> None:
    raise RuntimeError("Automatic schema downgrades are not supported.")
