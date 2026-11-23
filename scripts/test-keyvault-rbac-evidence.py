#!/usr/bin/env python3
"""Offline tests for controlled RBAC evidence collection."""

import importlib.util
import json
import pathlib
import subprocess
import uuid
import copy

ROOT = pathlib.Path(__file__).resolve().parent

spec = importlib.util.spec_from_file_location(
    "collector",
    ROOT / "collect-keyvault-rbac-evidence.py",
)
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)

vault = (
    f"/subscriptions/{collector.SUBSCRIPTION}"
    "/resourceGroups/rg-learningsteps-devsecops"
    "/providers/Microsoft.KeyVault/vaults/kv-lsteps-305c3ba6"
)

principal = str(uuid.uuid4())
assignment_id = (
    vault
    + "/providers/Microsoft.Authorization/roleAssignments/"
    + str(uuid.uuid4())
)

state = {
    "recovery_id": str(uuid.uuid4()),
    "vm_id": str(uuid.uuid4()),
    "principal_id": principal,
    "vault_id": vault,
    "assignment_id": assignment_id,
    "role": "Key Vault Secrets Officer",
    "status": "prepared",
}

assignment = {
    "id": assignment_id,
    "scope": vault,
    "principalId": principal,
    "roleDefinitionId": (
        f"/subscriptions/{collector.SUBSCRIPTION}"
        "/providers/Microsoft.Authorization/roleDefinitions/"
        + collector.ROLE_ID
    ),
}


def test(name, assignments, expected,
         account_id=None, account_rc=0, list_rc=0,
         invalid_json=False):

    calls = []

    def runner(command):
        calls.append(command)

        if command[:2] == ["account", "show"]:
            return subprocess.CompletedProcess(
                command,
                account_rc,
                json.dumps({
                    "id": account_id or collector.SUBSCRIPTION
                }),
                "",
            )

        assert command[:3] == [
            "role", "assignment", "list"
        ]
        assert "--scope" in command
        assert command[command.index("--scope") + 1] == vault
        assert "--subscription" in command
        assert command[
            command.index("--subscription") + 1
        ] == collector.SUBSCRIPTION

        return subprocess.CompletedProcess(
            command,
            list_rc,
            "invalid-json" if invalid_json
            else json.dumps(assignments),
            "",
        )

    try:
        result = collector.collect(state, runner)
        code = result["exit_code"]
    except (ValueError, KeyError, TypeError):
        code = 4

    assert code == expected, (
        f"{name}: expected {expected}, got {code}"
    )

    if account_rc != 0 or (
        account_id is not None
        and account_id != collector.SUBSCRIPTION
    ):
        assert len(calls) == 1
    else:
        assert len(calls) == 2

    print(f"PASS: {name} (exit={code})")


test("Confirmed absence", [], 0)
test("Interrupted grant", [assignment], 3)

test(
    "Account query failed",
    [], 4,
    account_rc=1,
)

test(
    "Wrong subscription",
    [], 4,
    account_id=str(uuid.uuid4()),
)

test(
    "RBAC query failed",
    [], 4,
    list_rc=1,
)

test(
    "Malformed Azure JSON",
    [], 4,
    invalid_json=True,
)

test(
    "Malformed RBAC response",
    {"unexpected": "object"}, 4,
)


# A modified Vault scope must be rejected before any Azure query.
tampered_state = copy.deepcopy(state)
tampered_state["vault_id"] = (
    vault.replace("kv-lsteps-305c3ba6", "unexpected-vault")
)

calls = []

def forbidden_runner(command):
    calls.append(command)
    raise AssertionError("Azure CLI must not be called")

try:
    collector.collect(tampered_state, forbidden_runner)
except ValueError as exc:
    assert "Unexpected recovery Vault scope" in str(exc)
else:
    raise AssertionError("Tampered Vault scope was accepted")

assert calls == [], "Azure CLI was invoked despite invalid scope"

print("PASS: Tampered Vault rejected before Azure query")

print("PASS: All eight RBAC evidence scenarios completed")
