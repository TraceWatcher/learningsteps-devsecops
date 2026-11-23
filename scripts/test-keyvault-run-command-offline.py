#!/usr/bin/env python3
"""Test actual Run Command adapter without contacting Azure."""

import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import uuid

SOURCE = pathlib.Path(__file__).resolve().parent

MOCK_AZ = r'''#!/usr/bin/env python3
import json
import os
import pathlib
import sys

args = sys.argv[1:]
counter = pathlib.Path(os.environ["MOCK_COUNTER"])

if args[:2] == ["vm", "show"]:
    count = int(counter.read_text()) + 1
    counter.write_text(str(count))

    vm_id = os.environ["MOCK_VM_ID"]
    if os.environ["MOCK_SCENARIO"] == "identity-change" and count > 1:
        vm_id = str(__import__("uuid").uuid4())

    print(json.dumps({
        "vmId": vm_id,
        "principalId": os.environ["MOCK_PRINCIPAL"],
    }))

elif args[:3] == ["vm", "run-command", "invoke"]:
    if "--scripts" not in args:
        sys.exit(91)

    marker = os.environ["MOCK_MARKER"]
    scenario = os.environ["MOCK_SCENARIO"]

    if scenario == "missing-marker":
        output = "Remote output without marker"
    elif scenario == "remote-failure":
        output = marker + "=12"
    else:
        output = marker + "=0"

    print(json.dumps({
        "value": [{
            "code": "ProvisioningState/succeeded",
            "message": "[stdout]\n" + output + "\n[stderr]\n",
        }]
    }))

else:
    print("Unexpected mock command", args, file=sys.stderr)
    sys.exit(99)
'''

with tempfile.TemporaryDirectory(prefix="ls-run-command-") as temp:
    root = pathlib.Path(temp)
    scripts = root / "scripts"
    recovery = root / "learningsteps-recovery"
    scripts.mkdir()
    recovery.mkdir(mode=0o700)

    shutil.copy2(
        SOURCE / "run-keyvault-recovery-command.sh",
        scripts / "run-keyvault-recovery-command.sh",
    )
    shutil.copy2(
        SOURCE / "verify-run-command-result.py",
        scripts / "verify-run-command-result.py",
    )

    rbac = scripts / "recovery-keyvault-rbac.sh"
    rbac.write_text(
        '#!/bin/sh\n'
        '[ "$1" = "status" ] || exit 99\n'
        'exit 0\n'
    )
    rbac.chmod(0o700)

    az = root / "mock-az"
    az.write_text(MOCK_AZ)
    az.chmod(0o700)

    payload = root / "payload.sh"
    payload.write_text("#!/bin/sh\nexit 0\n")
    payload.chmod(0o600)

    vm_id = str(uuid.uuid4())
    principal = str(uuid.uuid4())
    counter = root / "vm-counter"

    state = recovery / "temporary-keyvault-rbac.json"
    state.write_text(json.dumps({
        "recovery_id": str(uuid.uuid4()),
        "vm_id": vm_id,
        "principal_id": principal,
        "status": "granted",
    }))
    state.chmod(0o600)

    env = dict(os.environ)
    env.update({
        "HOME": str(root),
        "LS_MOCK_AZ": str(az),
        "MOCK_VM_ID": vm_id,
        "MOCK_PRINCIPAL": principal,
        "MOCK_COUNTER": str(counter),
    })

    adapter = scripts / "run-keyvault-recovery-command.sh"

    def run(mode, scenario):
        counter.write_text("0")
        env["MOCK_SCENARIO"] = scenario
        env["MOCK_MARKER"] = (
            "__LS_INSTALL_RC__"
            if mode == "--install"
            else "__LS_RESTORE_RC__"
        )

        return subprocess.run(
            [
                "bash",
                str(adapter),
                "--offline-test",
                mode,
                str(payload),
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=20,
        )

    cases = [
        ("--install", "success", True),
        ("--restore", "success", True),
        ("--install", "missing-marker", False),
        ("--restore", "remote-failure", False),
        ("--restore", "identity-change", False),
    ]

    for mode, scenario, expected_success in cases:
        result = run(mode, scenario)
        actual_success = result.returncode == 0

        assert actual_success == expected_success, (
            f"{mode}, {scenario}\n"
            f"Exit: {result.returncode}\n"
            f"{result.stdout}\n{result.stderr}"
        )

        assert int(counter.read_text()) == 2, (
            f"VM identity was not checked twice: {mode}, {scenario}"
        )

        print(
            f"PASS: {mode} / {scenario} "
            f"-> exit {result.returncode}"
        )

    print("PASS: Offline Run Command integration tests completed")
    print("PASS: No real Azure CLI invoked")
