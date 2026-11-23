#!/usr/bin/env python3
"""Synthetic offline tests for recovery RBAC reconciliation."""

import copy
import importlib.util
import pathlib
import uuid

ROOT = pathlib.Path(__file__).resolve().parent

spec = importlib.util.spec_from_file_location(
    "reconciliation",
    ROOT / "check-keyvault-rbac-reconciliation.py",
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

vault = (
    "/subscriptions/901cb597-1248-4bc6-8b92-0452114c48b9"
    "/resourceGroups/rg-learningsteps-devsecops"
    "/providers/Microsoft.KeyVault/vaults/kv-lsteps-305c3ba6"
)

principal = str(uuid.uuid4())
role_id = str(uuid.uuid4())
assignment_id = (
    vault
    + "/providers/Microsoft.Authorization/roleAssignments/"
    + str(uuid.uuid4())
)

base_state = {
    "recovery_id": str(uuid.uuid4()),
    "vm_id": str(uuid.uuid4()),
    "principal_id": principal,
    "vault_id": vault,
    "assignment_id": assignment_id,
    "role": "Key Vault Secrets Officer",
    "status": "prepared",
}

base_assignment = {
    "id": assignment_id,
    "scope": vault,
    "principalId": principal,
    "roleDefinitionId": (
        "/subscriptions/901cb597-1248-4bc6-8b92-0452114c48b9"
        "/providers/Microsoft.Authorization/roleDefinitions/"
        + role_id
    ),
}


def test(name, status, present, expected,
         change_state=None, change_assignment=None):
    state = copy.deepcopy(base_state)
    state["status"] = status

    assignment = copy.deepcopy(base_assignment)

    if change_state:
        change_state(state)
    if change_assignment:
        change_assignment(assignment)

    entries = [assignment] if present else []

    try:
        result = module.reconcile(state, entries, role_id)
        code = result["exit_code"]
    except (ValueError, TypeError, KeyError):
        code = 4

    assert code == expected, (
        f"{name}: expected {expected}, got {code}"
    )
    print(f"PASS: {name} (exit={code})")


test("Prepared without grant", "prepared", False, 0)
test("Granted with matching grant", "granted", True, 0)
test("Removed without grant", "removed", False, 0)

test("Interrupted grant", "prepared", True, 3)
test("Missing granted assignment", "granted", False, 3)
test("Removed but grant remains", "removed", True, 4)

test(
    "Wrong principal",
    "granted", True, 4,
    change_assignment=lambda a: a.update(
        principalId=str(uuid.uuid4())
    ),
)

test(
    "Wrong role",
    "granted", True, 4,
    change_assignment=lambda a: a.update(
        roleDefinitionId=str(uuid.uuid4())
    ),
)

test(
    "Wrong scope",
    "granted", True, 4,
    change_assignment=lambda a: a.update(
        scope="/subscriptions/invalid"
    ),
)

test(
    "Wrong assignment ID",
    "granted", True, 4,
    change_assignment=lambda a: a.update(
        id=str(uuid.uuid4())
    ),
)

test(
    "Invalid local assignment scope",
    "granted", True, 4,
    change_state=lambda s: s.update(
        assignment_id=str(uuid.uuid4())
    ),
)

print("PASS: All 11 RBAC reconciliation scenarios completed")
