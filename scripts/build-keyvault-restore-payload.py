#!/usr/bin/env python3
"""Generate the fixed Key Vault restore command offline."""

import argparse
import ipaddress
import json
import os
import pathlib
import shlex
import stat
import uuid

VAULT = "kv-lsteps-305c3ba6"
REMOTE_SCRIPT = (
    "/opt/learningsteps-recovery/remote-restore-keyvault.py"
)


def load_state(path):
    info = path.lstat()

    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o600
    ):
        raise RuntimeError("Unsafe RBAC state file")

    state = json.loads(path.read_text(encoding="utf-8"))

    vm_id = str(uuid.UUID(state["vm_id"]))
    uuid.UUID(state["principal_id"])
    uuid.UUID(state["recovery_id"])

    if state.get("status") != "granted":
        raise RuntimeError("Recovery grant is not confirmed")

    if state.get("role") != "Key Vault Secrets Officer":
        raise RuntimeError("Unexpected recovery role")

    return vm_id


def build_payload(vm_id, private_ip):
    command = [
        "python3",
        REMOTE_SCRIPT,
        "--vault",
        VAULT,
        "--private-ip",
        private_ip,
        "--expected-vm-id",
        vm_id,
        "--execute",
    ]

    command_line = shlex.join(command)

    return (
        "#!/usr/bin/env bash\n"
        "set +e\n"
        "(\n"
        "  set -euo pipefail\n"
        "  umask 077\n"
        "  test \"$(id -u)\" = 0\n"
        f"  {command_line}\n"
        ")\n"
        "rc=$?\n"
        "printf '__LS_RESTORE_RC__=%s\\n' \"$rc\"\n"
        "exit 0\n"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True)
    parser.add_argument("--private-ip", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    private_ip = ipaddress.IPv4Address(args.private_ip)

    if not private_ip.is_private:
        raise RuntimeError("Public Key Vault endpoint rejected")

    vm_id = load_state(pathlib.Path(args.state))
    payload = build_payload(vm_id, str(private_ip))

    output = pathlib.Path(args.output)

    fd = os.open(
        output,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )

    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(payload)

    print("PASS: Fixed restore payload generated")
    print("INFO: No Azure commands executed")
    print("INFO: No passwords or tokens embedded")


if __name__ == "__main__":
    main()
