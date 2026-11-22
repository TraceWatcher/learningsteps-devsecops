#!/usr/bin/env python3

import argparse
import json
import os
import pathlib
import sys
import uuid

STATE_DIR = pathlib.Path.home() / "learningsteps-recovery"
STATE_FILE = STATE_DIR / "temporary-keyvault-rbac.json"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "operation",
        choices=["prepare", "show"],
    )
    parser.add_argument("--vault-id")
    parser.add_argument("--principal-id")
    parser.add_argument("--vm-id")

    args = parser.parse_args()

    if args.operation == "show":
        if not STATE_FILE.exists():
            print("INFO: No temporary RBAC record")
            return 0

        state = json.loads(STATE_FILE.read_text())
        print("Assignment ID:", state["assignment_id"])
        print("State:", state["status"])
        print("VM ID:", state["vm_id"])
        return 0

    if not all((
        args.vault_id,
        args.principal_id,
        args.vm_id,
    )):
        raise ValueError("Missing target identity")

    STATE_DIR.mkdir(mode=0o700, exist_ok=True)

    if STATE_FILE.exists():
        raise RuntimeError(
            "RBAC recovery record already exists; "
            "review it before continuing"
        )

    assignment_name = str(uuid.uuid4())
    assignment_id = (
        args.vault_id.rstrip("/")
        + "/providers/Microsoft.Authorization/"
        + "roleAssignments/"
        + assignment_name
    )

    state = {
        "assignment_id": assignment_id,
        "vault_id": args.vault_id,
        "principal_id": args.principal_id,
        "vm_id": args.vm_id,
        "role": "Key Vault Secrets Officer",
        "status": "prepared",
    }

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(STATE_FILE, flags, 0o600)

    with os.fdopen(fd, "w") as output:
        json.dump(state, output, indent=2)
        output.write("\n")

    print("PASS: RBAC assignment record prepared")
    print("INFO: No Azure role assignment created")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(
            f"ERROR: {type(exc).__name__}: "
            "RBAC state operation failed",
            file=sys.stderr,
        )
        sys.exit(1)
