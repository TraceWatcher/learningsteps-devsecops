#!/usr/bin/env python3
"""Offline integrity tests for the Key Vault restore payload."""

import importlib.util
import json
import pathlib
import shutil
import tempfile
import uuid

ROOT = pathlib.Path(__file__).resolve().parent

spec = importlib.util.spec_from_file_location(
    "payload_verifier",
    ROOT / "verify-keyvault-payload.py",
)
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)

generator = verifier.load_module("build-keyvault-restore-payload.py")

source_snapshot = (
    pathlib.Path.home()
    / "learningsteps-recovery/keyvault-network-snapshot.json"
)

with tempfile.TemporaryDirectory() as tmp:
    root = pathlib.Path(tmp)

    payloads = root / "payloads"
    payloads.mkdir(mode=0o700)

    payload = payloads / "restore.sh"
    state_file = root / "state.json"
    snapshot = root / "snapshot.json"

    shutil.copy2(source_snapshot, snapshot)
    snapshot.chmod(0o600)

    vm_id = str(uuid.uuid4())
    vault_id = generator.EXPECTED_VAULT_ID

    state = {
        "recovery_id": str(uuid.uuid4()),
        "vm_id": vm_id,
        "principal_id": str(uuid.uuid4()),
        "vault_id": vault_id,
        "assignment_id": (
            vault_id
            + "/providers/Microsoft.Authorization/roleAssignments/"
            + str(uuid.uuid4())
        ),
        "role": "Key Vault Secrets Officer",
        "status": "granted",
    }

    def save_state():
        state_file.write_text(json.dumps(state))
        state_file.chmod(0o600)

    def write_payload(data):
        payload.write_bytes(data)
        payload.chmod(0o600)

    def rejected(name):
        try:
            verifier.verify(
                "restore", payload, state_file, snapshot
            )
        except (ValueError, RuntimeError, OSError):
            print(f"PASS: {name} rejected")
        else:
            raise AssertionError(
                f"SECURITY FAILURE: {name} accepted"
            )

    save_state()

    original = verifier.expected_restore(
        state_file, snapshot
    )
    write_payload(original)

    assert verifier.verify(
        "restore", payload, state_file, snapshot
    ) == len(original)

    print("PASS: Original restore payload accepted")

    write_payload(original + b"\necho UNAUTHORIZED\n")
    rejected("Manipulated restore command")

    write_payload(
        generator.build_payload(
            vm_id, "10.30.3.99"
        ).encode("utf-8")
    )
    rejected("Wrong private IP")

    write_payload(original)
    state["vm_id"] = str(uuid.uuid4())
    save_state()
    rejected("Changed recovery VM identity")

    state["vm_id"] = vm_id
    save_state()

    data = json.loads(snapshot.read_text())
    data["record"]["aRecords"][0]["ipv4Address"] = "10.30.3.99"
    snapshot.write_text(json.dumps(data))
    rejected("Manipulated network snapshot")

print("PASS: All five restore payload scenarios completed")
