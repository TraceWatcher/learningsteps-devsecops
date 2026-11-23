#!/usr/bin/env python3
"""Offline integration of the real recovery controller and adapter."""

import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import uuid

SOURCE = pathlib.Path(__file__).resolve().parent

STEP_STUB = r'''#!/usr/bin/env bash
set -euo pipefail

NAME="$(basename "$0")"
LOG="${LS_TEST_LOG:?}"
SCENARIO="${LS_TEST_SCENARIO:?}"

case "$NAME" in
  prepare-keyvault-transport.sh)
    [[ $# -eq 0 ]] || exit 99
    STEP="preflight"
    ;;
  transport-keyvault-password.sh)
    [[ $# -eq 1 && "$1" == "--transfer" ]] || exit 99
    STEP="transport"
    ;;
  *)
    exit 99
    ;;
esac

printf '%s\n' "$STEP" >> "$LOG"

if [[ "$SCENARIO:$STEP" == "transport-fails:transport" ]]; then
  exit 21
fi
'''

RBAC_STUB = r'''#!/usr/bin/env python3
import json
import os
import pathlib
import sys

state_path = pathlib.Path(os.environ["LS_STATE"])
log_path = pathlib.Path(os.environ["LS_TEST_LOG"])
scenario = os.environ["LS_TEST_SCENARIO"]
mode = sys.argv[1:]

if len(mode) != 1:
    sys.exit(99)

state = json.loads(state_path.read_text())

def save(status):
    state["status"] = status
    state_path.write_text(json.dumps(state))

if mode == ["status"]:
    if state["status"] != "granted":
        sys.exit(3)
    sys.exit(0)

if mode == ["grant"]:
    with log_path.open("a") as f:
        f.write("grant\n")

    if state["status"] != "prepared":
        sys.exit(99)

    # Simulate a grant that reached Azure before its
    # controller reported an error.
    save("granted")

    if scenario == "grant-fails":
        sys.exit(22)

    sys.exit(0)

if mode == ["cleanup-auto"]:
    with log_path.open("a") as f:
        f.write("cleanup\n")

    if state["status"] != "granted":
        sys.exit(3)

    if scenario == "cleanup-fails":
        sys.exit(24)

    save("removed")
    sys.exit(0)

sys.exit(99)
'''

AZ_STUB = r'''#!/usr/bin/env python3
import json
import os
import pathlib
import sys

args = sys.argv[1:]

if args[:2] == ["vm", "show"]:
    with open(os.environ["LS_VM_COUNT"], "a") as f:
        f.write("1\n")

    print(json.dumps({
        "vmId": os.environ["LS_VM_ID"],
        "principalId": os.environ["LS_PRINCIPAL"],
    }))
    sys.exit(0)

if args[:3] == ["vm", "run-command", "invoke"]:
    if "--scripts" not in args:
        sys.exit(99)

    payload = args[args.index("--scripts") + 1]

    if not payload.startswith("@"):
        sys.exit(99)

    name = pathlib.Path(payload[1:]).name

    if name == "install.sh":
        step = "install"
        marker = "__LS_INSTALL_RC__"
    elif name == "restore.sh":
        step = "restore"
        marker = "__LS_RESTORE_RC__"
    else:
        sys.exit(99)

    with open(os.environ["LS_TEST_LOG"], "a") as f:
        f.write(step + "\n")

    rc = 0
    if (
        os.environ["LS_TEST_SCENARIO"] == "restore-fails"
        and step == "restore"
    ):
        rc = 23

    print(json.dumps({
        "value": [{
            "code": "ProvisioningState/succeeded",
            "message": (
                "[stdout]\n"
                + f"{marker}={rc}\n"
                + "[stderr]\n"
            ),
        }]
    }))
    sys.exit(0)

print("Unexpected Azure mock command", file=sys.stderr)
sys.exit(99)
'''

CASES = {
    "success": (
        0,
        ["preflight", "transport", "install",
         "grant", "restore", "cleanup"],
        "removed",
        4,
    ),
    "transport-fails": (
        21,
        ["preflight", "transport"],
        "prepared",
        0,
    ),
    "grant-fails": (
        22,
        ["preflight", "transport", "install",
         "grant", "cleanup"],
        "removed",
        2,
    ),
    "restore-fails": (
        1,
        ["preflight", "transport", "install",
         "grant", "restore", "cleanup"],
        "removed",
        4,
    ),
    "cleanup-fails": (
        90,
        ["preflight", "transport", "install",
         "grant", "restore", "cleanup"],
        "granted",
        4,
    ),
    "network-fails": (
        1,
        ["preflight", "transport", "install", "grant", "cleanup"],
        "removed",
        2,
    ),
}


def executable(path, content):
    path.write_text(content)
    path.chmod(0o700)


with tempfile.TemporaryDirectory(prefix="ls-recovery-e2e-") as tmp:
    root = pathlib.Path(tmp)
    scripts = root / "scripts"
    home = root / "home"
    recovery = home / "learningsteps-recovery"
    payloads = scripts / "payloads"

    scripts.mkdir()
    home.mkdir()
    recovery.mkdir(mode=0o700)
    payloads.mkdir()

    # Real controller, adapter and response validator.
    for name in (
        "execute-keyvault-recovery.sh",
        "run-keyvault-recovery-command.sh",
        "verify-run-command-result.py",
        "build-keyvault-install-payload.py",
        "build-keyvault-restore-payload.py",
        "restore-keyvault-secret.py",
        "remote-restore-keyvault.py",
        "validate-keyvault-network.py",
    ):
        shutil.copy2(SOURCE / name, scripts / name)

    # Copy the real Azure network snapshot into the test environment.
    snapshot_source = (
        pathlib.Path.home()
        / "learningsteps-recovery/keyvault-network-snapshot.json"
    )

    shutil.copy2(
        snapshot_source,
        scripts / "keyvault-network-snapshot.json",
    )

    (scripts / "execute-keyvault-recovery.sh").chmod(0o700)
    (scripts / "run-keyvault-recovery-command.sh").chmod(0o700)

    # Isolated stand-ins for transport and recovery checks.
    for name in (
        "prepare-keyvault-transport.sh",
        "transport-keyvault-password.sh",
    ):
        executable(scripts / name, STEP_STUB)

    executable(
        scripts / "recovery-keyvault-rbac.sh",
        RBAC_STUB,
    )

    mock_az = root / "mock-az"
    executable(mock_az, AZ_STUB)

    vm_id = str(uuid.uuid4())
    principal = str(uuid.uuid4())
    recovery_id = str(uuid.uuid4())

    state_path = recovery / "temporary-keyvault-rbac.json"
    log = root / "operations.log"
    vm_count = root / "vm-count.log"

    env = dict(os.environ)
    env.update({
        "HOME": str(home),
        "LS_INTEGRATION_ROOT": str(scripts),
        "LS_MOCK_AZ": str(mock_az),
        "LS_TEST_LOG": str(log),
        "LS_STATE": str(state_path),
        "LS_VM_COUNT": str(vm_count),
        "LS_VM_ID": vm_id,
        "LS_PRINCIPAL": principal,
    })

    controller = scripts / "execute-keyvault-recovery.sh"

    for scenario, (
        expected_rc,
        expected_steps,
        expected_status,
        expected_vm_queries,
    ) in CASES.items():

        log.write_text("")
        vm_count.write_text("")

        # Remove generated payloads from the previous scenario.
        for name in ("install.sh", "restore.sh"):
            (payloads / name).unlink(missing_ok=True)

        state_path.write_text(json.dumps({
            "recovery_id": recovery_id,
            "vm_id": vm_id,
            "principal_id": principal,
            "role": "Key Vault Secrets Officer",
            "status": "prepared",
            "vault_id": (
                "/subscriptions/901cb597-1248-4bc6-8b92-0452114c48b9"
                "/resourceGroups/rg-learningsteps-devsecops"
                "/providers/Microsoft.KeyVault/vaults/kv-lsteps-305c3ba6"
            ),
            "assignment_id": (
                "/subscriptions/901cb597-1248-4bc6-8b92-0452114c48b9"
                "/resourceGroups/rg-learningsteps-devsecops"
                "/providers/Microsoft.KeyVault/vaults/kv-lsteps-305c3ba6"
                "/providers/Microsoft.Authorization/roleAssignments/"
                + str(uuid.uuid4())
            ),
        }))
        state_path.chmod(0o600)

        snapshot_path = scripts / "keyvault-network-snapshot.json"

        snapshot_data = json.loads(snapshot_source.read_text())

        if scenario == "network-fails":
            snapshot_data["record"]["aRecords"][0]["ipv4Address"] = "10.30.3.99"

        snapshot_path.write_text(json.dumps(snapshot_data))
        snapshot_path.chmod(0o600)

        env["LS_TEST_SCENARIO"] = scenario

        result = subprocess.run(
            ["bash", str(controller), "--integration-test"],
            env=env,
            capture_output=True,
            text=True,
            timeout=25,
        )

        if scenario == "network-fails":
            assert not (payloads / "restore.sh").exists(), (
                "SECURITY FAILURE: Restore payload generated "
                "despite invalid network configuration"
            )
            print("PASS: Invalid network blocked restore payload generation")

        steps = log.read_text().splitlines()
        status = json.loads(state_path.read_text())["status"]
        queries = len(vm_count.read_text().splitlines())

        assert result.returncode == expected_rc, (
            f"{scenario}: unexpected exit {result.returncode}\n"
            f"{result.stdout}\n{result.stderr}"
        )

        assert steps == expected_steps, (
            f"{scenario}: unexpected steps {steps}\n"
            f"Expected: {expected_steps}"
        )

        assert status == expected_status, (
            f"{scenario}: unexpected RBAC status {status}"
        )

        assert queries == expected_vm_queries, (
            f"{scenario}: expected {expected_vm_queries} "
            f"VM queries, got {queries}"
        )

        print(
            f"PASS: {scenario:16} "
            f"exit={result.returncode} "
            f"rbac={status} "
            f"vm_checks={queries}"
        )

    print("PASS: Combined controller/adapter integration completed")
    print("PASS: No real Azure CLI or infrastructure accessed")
