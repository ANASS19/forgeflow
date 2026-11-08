"""Exercise real CLI success/failure/history with synthetic data in temporary storage."""

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import cast

from pydantic import JsonValue

EXAMPLES = Path(__file__).resolve().parent


def cli(*arguments: str, expected: int = 0) -> dict[str, JsonValue]:
    completed = subprocess.run(
        [sys.executable, "-I", "-m", "forgeflow", *arguments, "--json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    if completed.returncode != expected:
        raise RuntimeError("The demonstration CLI returned an unexpected exit status.")
    return cast(dict[str, JsonValue], json.loads(completed.stdout))


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="forgeflow-demo-") as directory:
        options = ["--data-dir", directory]
        validated = cli("validate", str(EXAMPLES / "values.yaml"))
        doctor = cli("doctor", str(EXAMPLES / "values.yaml"))
        successful = cli("run", str(EXAMPLES / "values.yaml"), *options)
        failed = cli("run", str(EXAMPLES / "assertion-failure.yaml"), *options, expected=1)
        inspected = cli("inspect", str(failed["id"]), *options)
        history = cli("history", *options)
        assert validated["status"] == doctor["status"] == "valid"
        assert successful["state"] == "SUCCEEDED" and failed["state"] == "FAILED"
        steps, attempts, runs = inspected["steps"], inspected["attempts"], history["runs"]
        assert isinstance(steps, list) and isinstance(attempts, list) and isinstance(runs, list)
        states = {str(item["id"]): item["state"] for item in steps if isinstance(item, dict)}
        codes = [item["code"] for item in attempts if isinstance(item, dict) and item["code"]]
        assert states["blocked"] == "SKIPPED" and states["independent"] == "SUCCEEDED"
        assert codes == ["ASSERTION_FAILED"] and len(runs) == 2
        print(
            json.dumps(
                {
                    "validation": validated["status"],
                    "doctor": doctor["status"],
                    "successful_run": successful["state"],
                    "failed_run": failed["state"],
                    "failure_codes": codes,
                    "steps_after_failure": states,
                    "history_count": len(runs),
                    "network_requests": "none; this checkpoint executes pure steps only",
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
