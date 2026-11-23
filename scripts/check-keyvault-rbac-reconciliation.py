#!/usr/bin/env python3
"""Read-only comparison of local recovery state and Azure RBAC data."""

import argparse
import json
import os
import stat
import uuid
from pathlib import Path


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_json(path):
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode), "Not a regular file")
    require(info.st_uid == os.getuid(), "Unexpected file owner")
    require((info.st_mode & 0o077) == 0, "Unsafe file permissions")
    return json.loads(path.read_text())


def norm(value):
    require(isinstance(value, str), "Expected string identifier")
    return value.rstrip("/").casefold()


def parse_uuid(value):
    return str(uuid.UUID(str(value)))


def reconcile(state, assignments, expected_role_id):
    require(isinstance(state, dict), "Invalid recovery state")
    require(isinstance(assignments, list), "Invalid RBAC snapshot")

    status = state.get("status")
    require(status in ("prepared", "granted", "removed"),
            "Unknown recovery state")

    require(state.get("role") == "Key Vault Secrets Officer",
            "Unexpected local role")

    vault_id = norm(state["vault_id"])
    principal = parse_uuid(state["principal_id"])
    parse_uuid(state["vm_id"])
    parse_uuid(state["recovery_id"])

    assignment_id = norm(state["assignment_id"])
    prefix = vault_id + (
        "/providers/microsoft.authorization/roleassignments/"
    )
    require(assignment_id.startswith(prefix),
            "Assignment outside expected Key Vault")

    assignment_uuid = assignment_id[len(prefix):]
    require("/" not in assignment_uuid, "Malformed assignment path")
    parse_uuid(assignment_uuid)

    expected_role = parse_uuid(expected_role_id)
    subscription = vault_id.split("/")[2]

    expected_role_resource_id = (
        f"/subscriptions/{subscription}"
        "/providers/microsoft.authorization/roledefinitions/"
        f"{expected_role}"
    )

    matches = []
    suspicious = []

    for assignment in assignments:
        require(isinstance(assignment, dict), "Invalid assignment entry")

        entry_id = norm(assignment["id"])
        entry_scope = norm(assignment["scope"])
        entry_principal = parse_uuid(assignment["principalId"])
        role_id = norm(assignment["roleDefinitionId"])

        same_assignment = entry_id == assignment_id
        same_identity_scope = (
            entry_scope == vault_id and entry_principal == principal
        )


        if same_assignment:
            require(
                entry_scope == vault_id
                and entry_principal == principal
                and role_id == expected_role_resource_id,
                "SECURITY: Assignment fields do not match",
            )
            matches.append(assignment)


        elif same_identity_scope:
            suspicious.append(entry_id)

    require(len(matches) <= 1, "Duplicate assignment IDs")
    require(not suspicious,
            "SECURITY: Additional assignments for recovery identity")

    present = len(matches) == 1

    if status == "prepared" and not present:
        result = ("consistent", "No assignment exists", 0)
    elif status == "granted" and present:
        result = ("consistent", "Expected assignment exists", 0)
    elif status == "removed" and not present:
        result = ("consistent", "Assignment removed", 0)
    elif status == "prepared" and present:
        result = ("interrupted-grant", "Grant exists but state is prepared", 3)
    elif status == "granted" and not present:
        result = ("drift", "Grant missing despite granted state", 3)
    else:
        result = ("security-mismatch", "Removed state still has grant", 4)

    return {
        "classification": result[0],
        "message": result[1],
        "local_status": status,
        "azure_assignment_present": present,
        "exit_code": result[2],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--assignments", type=Path, required=True)
    parser.add_argument("--expected-role-id", required=True)
    args = parser.parse_args()

    try:
        state = read_json(args.state)
        assignments = read_json(args.assignments)
        result = reconcile(
            state, assignments, args.expected_role_id
        )
    except (OSError, KeyError, TypeError, ValueError) as exc:
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
