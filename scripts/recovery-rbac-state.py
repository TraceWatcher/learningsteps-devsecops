#!/usr/bin/env python3

import argparse
import json
import os
import pathlib
import sys
import uuid
import fcntl
import stat
import tempfile

STATE_DIR = pathlib.Path.home() / "learningsteps-recovery"
STATE_FILE = STATE_DIR / "temporary-keyvault-rbac.json"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "operation",
        choices=["prepare", "show", "update"],
    )
    parser.add_argument("--vault-id")
    parser.add_argument("--principal-id")
    parser.add_argument("--vm-id")
    parser.add_argument(
        "--status",
        choices=["granted", "removed"],
    )

    args = parser.parse_args()


    if args.operation == "update":
        if args.status is None:
            raise ValueError("Missing --status")

        if STATE_FILE.is_symlink() or not STATE_FILE.is_file():
            raise RuntimeError("RBAC state missing or unsafe")

        metadata = STATE_FILE.stat()

        if stat.S_IMODE(metadata.st_mode) != 0o600:
            raise RuntimeError("Unsafe RBAC state permissions")

        if metadata.st_uid != os.getuid():
            raise RuntimeError("Unexpected RBAC state owner")

        lock_path = STATE_DIR / ".temporary-keyvault-rbac.lock"

        if lock_path.is_symlink():
            raise RuntimeError("Unsafe RBAC lock file")

        fd_lock = os.open(
            lock_path,
            os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW,
            0o600,
        )

        with os.fdopen(fd_lock, "r+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)

            state = json.loads(STATE_FILE.read_text())
            current = state.get("status")

            allowed = {
                "prepared": {"granted", "removed"},
                "granted": {"removed"},
                "removed": set(),
            }

            if current not in allowed:
                raise RuntimeError("Unknown RBAC state")

            if args.status == current:
                print("INFO: RBAC state already up to date")
                return 0

            if args.status not in allowed[current]:
                raise RuntimeError("Invalid RBAC state transition")

            state["status"] = args.status

            temp_name = None

            try:
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    dir=STATE_DIR,
                    prefix=".rbac-state-",
                    suffix=".tmp",
                    delete=False,
                ) as output:
                    temp_name = output.name
                    os.chmod(temp_name, 0o600)
                    json.dump(state, output, indent=2)
                    output.write("\n")
                    output.flush()
                    os.fsync(output.fileno())

                os.replace(temp_name, STATE_FILE)

                directory_fd = os.open(
                    STATE_DIR, os.O_RDONLY | os.O_DIRECTORY
                )
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)

            finally:
                if temp_name and os.path.exists(temp_name):
                    os.unlink(temp_name)

        print(f"PASS: RBAC state updated to {args.status}")
        return 0


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

    recovery_id = str(uuid.uuid4())
    assignment_name = str(uuid.uuid4())
    assignment_id = (
        args.vault_id.rstrip("/")
        + "/providers/Microsoft.Authorization/"
        + "roleAssignments/"
        + assignment_name
    )

    state = {
        "recovery_id": recovery_id,
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
