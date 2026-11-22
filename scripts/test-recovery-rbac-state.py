#!/usr/bin/env python3

import json
import os
import pathlib
import stat
import subprocess
import sys
import tempfile

SCRIPT = pathlib.Path(
    "scripts/recovery-rbac-state.py"
).resolve()

VAULT = (
    "/subscriptions/00000000-0000-0000-0000-000000000000"
    "/resourceGroups/test-rg"
    "/providers/Microsoft.KeyVault/vaults/test-vault"
)


def run(env, *args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        env=env,
        capture_output=True,
        text=True,
    )


with tempfile.TemporaryDirectory() as temp:
    env = dict(os.environ, HOME=temp)

    state_file = (
        pathlib.Path(temp)
        / "learningsteps-recovery"
        / "temporary-keyvault-rbac.json"
    )

    print("[1/5] Preparing RBAC state")

    result = run(
        env, "prepare",
        "--vault-id", VAULT,
        "--principal-id", "test-principal",
        "--vm-id", "test-vm",
    )
    assert result.returncode == 0, result.stderr

    original = json.loads(state_file.read_text())
    assert original["status"] == "prepared"
    print("PASS: State prepared")

    print("[2/5] Transition prepared -> granted")

    result = run(env, "update", "--status", "granted")
    assert result.returncode == 0, result.stderr

    granted = json.loads(state_file.read_text())
    assert granted["status"] == "granted"
    assert granted["assignment_id"] == original["assignment_id"]
    assert granted["recovery_id"] == original["recovery_id"]
    print("PASS: Granted state persisted")

    print("[3/5] Repeating granted update")

    result = run(env, "update", "--status", "granted")
    assert result.returncode == 0, result.stderr
    assert json.loads(state_file.read_text()) == granted
    print("PASS: Repeated update is idempotent")

    print("[4/5] Transition granted -> removed")

    result = run(env, "update", "--status", "removed")
    assert result.returncode == 0, result.stderr

    removed = json.loads(state_file.read_text())
    assert removed["status"] == "removed"
    assert removed["assignment_id"] == original["assignment_id"]
    print("PASS: Removed state persisted")

    print("[5/5] Rejecting invalid transition")

    result = run(env, "update", "--status", "granted")
    assert result.returncode != 0

    assert json.loads(state_file.read_text()) == removed

    assert stat.S_IMODE(
        state_file.stat().st_mode
    ) == 0o600

    print("PASS: Invalid transition rejected")
    print("PASS: File permissions remain 0600")

print("PASS: All RBAC state lifecycle tests completed")
