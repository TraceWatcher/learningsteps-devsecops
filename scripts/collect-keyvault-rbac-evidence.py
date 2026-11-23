#!/usr/bin/env python3
"""Offline-only RBAC collector and reconciliation integration."""

import argparse
import importlib.util
import json
import subprocess
from pathlib import Path

SUBSCRIPTION = "901cb597-1248-4bc6-8b92-0452114c48b9"
ROLE_ID = "b86a8fe4-44ce-4948-aee5-eccb2c155cd7"

ROOT = Path(__file__).resolve().parent

spec = importlib.util.spec_from_file_location(
    "reconciliation",
    ROOT / "check-keyvault-rbac-reconciliation.py",
)
reconciliation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reconciliation)


def azure_json(runner, *args):
    result = runner(list(args))

    if result.returncode != 0:
        raise ValueError(
            "Azure CLI query failed; refusing to infer missing RBAC"
        )

    if result.stderr.strip():
        raise ValueError("Azure CLI reported stderr output")

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("Invalid Azure CLI JSON response") from exc


def collect(state, runner):
    # Query account identity first.
    account = azure_json(runner, "account", "show", "-o", "json")

    if not isinstance(account, dict):
        raise ValueError("Invalid Azure account response")

    if account.get("id", "").casefold() != SUBSCRIPTION.casefold():
        raise ValueError("Unexpected Azure subscription")

    # The scope comes from state, but reconciliation validates it.
    # Never infer missing assignments from a failed CLI request.
    scope = state["vault_id"]

    assignments = azure_json(
        runner,
        "role", "assignment", "list",
        "--scope", scope,
        "--all",
        "--subscription", SUBSCRIPTION,
        "-o", "json",
    )

    if not isinstance(assignments, list):
        raise ValueError("RBAC response is not an array")

    return reconciliation.reconcile(
        state,
        assignments,
        ROLE_ID,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline-test", action="store_true")
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--mock-az", type=Path)
    args = parser.parse_args()

    # No live Azure capability in this script.
    if not args.offline_test or args.mock_az is None:
        parser.error("Only --offline-test with --mock-az is supported")

    mock = args.mock_az.resolve(strict=True)
    if not mock.is_file():
        parser.error("Invalid mock executable")

    try:
        state = reconciliation.read_json(args.state)

        def runner(command):
            return subprocess.run(
                [str(mock), *command],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )

        result = collect(state, runner)
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.TimeoutExpired,
    ) as exc:
        print(json.dumps({
            "classification": "security-mismatch",
            "message": str(exc),
            "exit_code": 4,
        }))
        return 4

    print(json.dumps(result, indent=2))
    return result["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
