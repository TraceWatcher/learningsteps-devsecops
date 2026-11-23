#!/usr/bin/env python3
"""Offline integration test of the actual Run Command adapter."""

import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import uuid

SOURCE = pathlib.Path(__file__).resolve().parent
ADAPTER = SOURCE / "run-keyvault-recovery-command.sh"

with tempfile.TemporaryDirectory(prefix="ls-command-test-") as temp:
    root = pathlib.Path(temp)
    scripts = root / "scripts"
    bin_dir = root / "bin"
    backup = root / "learningsteps-recovery"

    scripts.mkdir()
    bin_dir.mkdir()
    backup.mkdir(mode=0o700)

    shutil.copy2(
        ADAPTER,
        scripts / "run-keyvault-recovery-command.sh",
    )

    # Replace target-check script with an offline stub.
    checker = scripts / "check-recovery-vm.sh"
    checker.write_text("#!/bin/sh\nexit 0\n")
    checker.chmod(0o700)

    rbac = scripts / "recovery-keyvault-rbac.sh"
    rbac.write_text(
        "#!/usr/bin/env bash\n"
        '[[ "$1" == "status" ]] || exit 99\n'
        '[[ "${MOCK_RBAC_OK:-1}" == "1" ]] || exit 3\n'
        'echo "PASS: Mock Azure RBAC confirmed"\n'
    )
    rbac.chmod(0o700)

    # Every unexpected Azure command fails.
    az = bin_dir / "az"
    az.write_text(
        "#!/usr/bin/env python3\n"
        "import os, sys\n"
        "if sys.argv[1:3] == ['vm', 'show']:\n"
        "    print(os.environ['MOCK_VM_JSON'])\n"
        "else:\n"
        "    print('Unexpected Azure command', file=sys.stderr)\n"
        "    sys.exit(99)\n"
    )
    az.chmod(0o700)

    payload = root / "payload.sh"
    payload.write_text("#!/bin/sh\nexit 0\n")

    vm_id = str(uuid.uuid4())
    principal = str(uuid.uuid4())

    state_path = backup / "temporary-keyvault-rbac.json"

    env = dict(os.environ)
    env["HOME"] = str(root)
    env["PATH"] = str(bin_dir) + os.pathsep + env["PATH"]

    env["MOCK_VM_JSON"] = json.dumps({
        "vmId": vm_id,
        "principalId": principal,
    })

    def run(status, mode, wrong_vm=False):
        state_path.write_text(json.dumps({
            "recovery_id": str(uuid.uuid4()),
            "vm_id": vm_id,
            "principal_id": principal,
            "status": status,
        }))
        state_path.chmod(0o600)

        if wrong_vm:
            env["MOCK_VM_JSON"] = json.dumps({
                "vmId": str(uuid.uuid4()),
                "principalId": principal,
            })
        else:
            env["MOCK_VM_JSON"] = json.dumps({
                "vmId": vm_id,
                "principalId": principal,
            })

        return subprocess.run(
            [
                "bash",
                str(scripts / "run-keyvault-recovery-command.sh"),
                mode,
                str(payload),
            ],
            env=env,
            text=True,
            capture_output=True,
        )

    cases = [
        ("prepared", "--install", True),
        ("granted", "--install", True),
        ("removed", "--install", False),
        ("prepared", "--restore", False),
        ("granted", "--restore", True),
        ("removed", "--restore", False),
    ]

    for status, mode, expected in cases:
        result = run(status, mode)

        assert (result.returncode == 0) == expected, (
            f"{status} {mode}\n"
            f"{result.stdout}\n{result.stderr}"
        )

        print(f"PASS: {status:8} {mode:10}")


    # Test 7: Wrong VM identity must block execution.
    result = run("granted", "--restore", wrong_vm=True)

    assert result.returncode != 0, (
        "Wrong VM identity was accepted"
    )

    assert "Recovery VM identity mismatch" in (
        result.stdout + result.stderr
    )

    print("PASS: Wrong VM identity rejected")

    # Test 8: Missing Azure RBAC confirmation must block restore.
    env["MOCK_RBAC_OK"] = "0"

    result = run("granted", "--restore")

    assert result.returncode != 0, (
        "Restore accepted without confirmed Azure RBAC"
    )

    assert "Mock Azure RBAC confirmed" not in result.stdout

    print("PASS: Restore blocked when Azure RBAC is unconfirmed")

    print("PASS: Actual adapter tested with offline Azure stub")
    print("PASS: No real Azure operations executed")
