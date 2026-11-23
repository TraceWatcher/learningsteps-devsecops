
#!/usr/bin/env python3
"""Exercise the actual Run Command adapter without contacting Azure."""

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
import stat
import sys
import uuid

args = sys.argv[1:]
vm_counter = pathlib.Path(os.environ["MOCK_COUNTER"])
run_counter = pathlib.Path(os.environ["MOCK_RUN_COUNTER"])

if args[:2] == ["vm", "show"]:
    count = int(vm_counter.read_text()) + 1
    vm_counter.write_text(str(count))

    vm_id = os.environ["MOCK_VM_ID"]

    if os.environ["MOCK_SCENARIO"] == "identity-change" and count > 1:
        vm_id = str(uuid.uuid4())

    print(json.dumps({
        "vmId": vm_id,
        "principalId": os.environ["MOCK_PRINCIPAL"],
    }))

elif args[:3] == ["vm", "run-command", "invoke"]:
    # This counter records actual attempts to invoke Run Command.
    count = int(run_counter.read_text()) + 1
    run_counter.write_text(str(count))

    try:
        index = args.index("--scripts")
        argument = args[index + 1]

        if not argument.startswith("@"):
            raise ValueError("Missing payload file reference")

        payload = pathlib.Path(argument[1:])
        info = payload.lstat()

        if not payload.is_absolute():
            raise ValueError("Payload path is not absolute")

        if payload.parent.name != "verified":
            raise ValueError("Unverified payload submitted")

        if not stat.S_ISREG(info.st_mode):
            raise ValueError("Payload is not a regular file")

        if stat.S_IMODE(info.st_mode) != 0o600:
            raise ValueError("Unsafe payload permissions")

        if payload.name not in ("install.sh", "restore.sh"):
            raise ValueError("Unexpected payload name")

        expected_name = (
            "install.sh"
            if os.environ["MOCK_MODE"] == "--install"
            else "restore.sh"
        )

        if payload.name != expected_name:
            raise ValueError("Operation and payload differ")

        marker = os.environ["MOCK_MARKER"]

        if marker.encode() not in payload.read_bytes():
            raise ValueError("Expected marker missing")

    except (ValueError, OSError, IndexError) as exc:
        print(f"SECURITY: {exc}", file=sys.stderr)
        sys.exit(73)

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
    payloads = scripts / "payloads"

    scripts.mkdir()
    recovery.mkdir(mode=0o700)
    payloads.mkdir(mode=0o700)

    files = (
        "run-keyvault-recovery-command.sh",
        "verify-run-command-result.py",
        "verify-keyvault-payload.py",
        "build-keyvault-install-payload.py",
        "build-keyvault-restore-payload.py",
        "restore-keyvault-secret.py",
        "remote-restore-keyvault.py",
        "validate-keyvault-network.py",
    )

    for name in files:
        shutil.copy2(SOURCE / name, scripts / name)

    # Use the known original-environment snapshot only for offline testing.
    snapshot_source = (
        pathlib.Path.home()
        / "learningsteps-recovery/keyvault-network-snapshot.json"
    )

    snapshot = scripts / "keyvault-network-snapshot.json"
    shutil.copy2(snapshot_source, snapshot)
    snapshot.chmod(0o600)

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

    vault_id = (
        "/subscriptions/901cb597-1248-4bc6-8b92-0452114c48b9"
        "/resourceGroups/rg-learningsteps-devsecops"
        "/providers/Microsoft.KeyVault/vaults/kv-lsteps-305c3ba6"
    )

    vm_id = str(uuid.uuid4())
    principal = str(uuid.uuid4())

    state = recovery / "temporary-keyvault-rbac.json"
    state.write_text(json.dumps({
        "recovery_id": str(uuid.uuid4()),
        "vm_id": vm_id,
        "principal_id": principal,
        "vault_id": vault_id,
        "assignment_id": (
            vault_id
            + "/providers/Microsoft.Authorization/roleAssignments/"
            + str(uuid.uuid4())
        ),
        "role": "Key Vault Secrets Officer",
        "status": "granted",
    }))
    state.chmod(0o600)

    install_payload = payloads / "install.sh"
    restore_payload = payloads / "restore.sh"

    subprocess.run(
        [
            "python3",
            str(scripts / "build-keyvault-install-payload.py"),
            "--output",
            str(install_payload),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    subprocess.run(
        [
            "python3",
            str(scripts / "build-keyvault-restore-payload.py"),
            "--state",
            str(state),
            "--private-ip",
            "10.30.3.4",
            "--output",
            str(restore_payload),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    vm_counter = root / "vm-counter"
    run_counter = root / "run-command-counter"

    env = dict(os.environ)
    env.update({
        "HOME": str(root),
        "LS_MOCK_AZ": str(az),
        "MOCK_VM_ID": vm_id,
        "MOCK_PRINCIPAL": principal,
        "MOCK_COUNTER": str(vm_counter),
        "MOCK_RUN_COUNTER": str(run_counter),
    })

    adapter = scripts / "run-keyvault-recovery-command.sh"

    def run(mode, scenario, file=None):
        vm_counter.write_text("0")
        run_counter.write_text("0")

        env["MOCK_SCENARIO"] = scenario
        env["MOCK_MODE"] = mode
        env["MOCK_MARKER"] = (
            "__LS_INSTALL_RC__"
            if mode == "--install"
            else "__LS_RESTORE_RC__"
        )

        if file is None:
            file = (
                install_payload
                if mode == "--install"
                else restore_payload
            )

        result = subprocess.run(
            [
                "bash",
                str(adapter),
                "--offline-test",
                mode,
                str(file),
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=25,
        )

        return (
            result,
            int(vm_counter.read_text()),
            int(run_counter.read_text()),
        )

    # Original five scenarios, now using genuine generated payloads.
    cases = [
        ("--install", "success", True),
        ("--restore", "success", True),
        ("--install", "missing-marker", False),
        ("--restore", "remote-failure", False),
        ("--restore", "identity-change", False),
    ]

    for mode, scenario, expected_success in cases:
        result, vm_checks, run_calls = run(mode, scenario)

        assert (result.returncode == 0) == expected_success, (
            f"{mode}, {scenario}: exit {result.returncode}\n"
            f"{result.stdout}\n{result.stderr}"
        )

        assert vm_checks == 2, (
            f"{mode}, {scenario}: expected 2 VM checks, got {vm_checks}"
        )

        assert run_calls == 1, (
            f"{mode}, {scenario}: expected 1 Run Command, got {run_calls}"
        )

        print(f"PASS: {mode} / {scenario} -> exit {result.returncode}")

    # Attack 1: a modified installation payload.
    original = install_payload.read_bytes()

    install_payload.write_bytes(
        original + b"\necho UNAUTHORIZED\n"
    )
    install_payload.chmod(0o600)

    result, vm_checks, run_calls = run("--install", "success")

    assert result.returncode != 0
    assert run_calls == 0
    assert vm_checks == 1
    print("PASS: Tampered payload rejected before Run Command")

    # Restore the original test fixture.
    install_payload.write_bytes(original)
    install_payload.chmod(0o600)

    # Attack 2: submit an installation payload as a restore.
    result, vm_checks, run_calls = run(
        "--restore",
        "success",
        install_payload,
    )

    assert result.returncode != 0
    assert run_calls == 0
    assert vm_checks == 1
    print("PASS: Swapped operation rejected before Run Command")

    print("PASS: All seven direct adapter scenarios completed")
    print("PASS: No real Azure CLI invoked")
