#!/usr/bin/env python3
"""Isolated RBAC grant/cleanup integration test. No Azure access."""

import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import uuid

SOURCE = pathlib.Path(__file__).resolve().parents[1] / "scripts"

SUB = "901cb597-1248-4bc6-8b92-0452114c48b9"
VAULT = (
    f"/subscriptions/{SUB}"
    "/resourceGroups/rg-learningsteps-devsecops"
    "/providers/Microsoft.KeyVault/vaults/kv-lsteps-305c3ba6"
)
ROLE = (
    f"/subscriptions/{SUB}"
    "/providers/Microsoft.Authorization/roleDefinitions/"
    "00000000-0000-0000-0000-000000000001"
)

AZ_STUB = r'''#!/usr/bin/env python3
import json
import os
import pathlib
import sys

args = sys.argv[1:]
remote_path = pathlib.Path(os.environ["MOCK_REMOTE"])
log_path = pathlib.Path(os.environ["MOCK_LOG"])
remote = json.loads(remote_path.read_text())

def save():
    remote_path.write_text(json.dumps(remote))

def log(action):
    with log_path.open("a") as f:
        f.write(action + "\n")

if args[:2] == ["account", "show"]:
    print(os.environ["MOCK_SUB"])

elif args[:3] == ["role", "definition", "list"]:
    print(os.environ["MOCK_ROLE"])

elif args[:3] == ["role", "assignment", "list"]:
    print(json.dumps(remote))

elif args[:3] == ["role", "assignment", "create"]:
    log("CREATE")
    def arg(flag):
        return args[args.index(flag) + 1]

    if (
        arg("--name") != os.environ["MOCK_ASSIGNMENT"].split("/")[-1]
        or arg("--assignee-object-id") != os.environ["MOCK_PRINCIPAL"]
        or arg("--scope").lower() != os.environ["MOCK_VAULT"].lower()
        or arg("--role") != "Key Vault Secrets Officer"
    ):
        sys.exit(91)

    if remote:
        sys.exit(92)

    remote.append({
        "id": os.environ["MOCK_ASSIGNMENT"],
        "scope": os.environ["MOCK_VAULT"],
        "principalId": os.environ["MOCK_PRINCIPAL"],
        "roleDefinitionId": os.environ["MOCK_ROLE"],
    })
    save()

elif args[:3] == ["role", "assignment", "delete"]:
    log("DELETE")
    assignment = args[args.index("--ids") + 1]
    if assignment.lower() != os.environ["MOCK_ASSIGNMENT"].lower():
        sys.exit(93)
    remote = [
        r for r in remote
        if r["id"].lower() != assignment.lower()
    ]
    save()

elif args[:2] == ["vm", "show"]:
    print(json.dumps({
        "vmId": os.environ["MOCK_VM_ID"],
        "principalId": os.environ["MOCK_PRINCIPAL"],
    }))

else:
    print("Unexpected mock Azure command:", args, file=sys.stderr)
    sys.exit(99)
'''


def write_executable(path, content):
    path.write_text(content)
    path.chmod(0o700)


with tempfile.TemporaryDirectory(prefix="ls-rbac-test-") as temp:
    root = pathlib.Path(temp)
    scripts = root / "scripts"
    scripts.mkdir()

    bin_dir = root / "bin"
    bin_dir.mkdir()

    state_dir = root / "learningsteps-recovery"
    state_dir.mkdir(mode=0o700)

    state_file = state_dir / "temporary-keyvault-rbac.json"
    remote_file = root / "azure-state.json"
    log_file = root / "azure-writes.log"

    assignment = VAULT + (
        "/providers/Microsoft.Authorization/roleAssignments/"
        + str(uuid.uuid4())
    )
    principal = str(uuid.uuid4())
    vm_id = str(uuid.uuid4())

    base_state = {
        "recovery_id": str(uuid.uuid4()),
        "assignment_id": assignment,
        "vault_id": VAULT,
        "principal_id": principal,
        "vm_id": vm_id,
        "role": "Key Vault Secrets Officer",
    }

    # Execute the actual controller, with ROOT redirected to a sandbox.
    source = (SOURCE / "recovery-keyvault-rbac.sh").read_text()
    original_root = 'ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"'
    assert source.count(original_root) == 1
    source = source.replace(original_root, f'ROOT="{root}"')

    controller = scripts / "recovery-keyvault-rbac.sh"
    write_executable(controller, source)

    shutil.copy2(
        SOURCE / "recovery-rbac-state.py",
        scripts / "recovery-rbac-state.py",
    )

    write_executable(
        scripts / "prepare-keyvault-transport.sh",
        '#!/usr/bin/env bash\n'
        '[[ "${MOCK_PREFLIGHT:-allow}" == "allow" ]]\n',
    )
    write_executable(
        scripts / "run-keyvault-inspection.sh",
        '#!/usr/bin/env bash\n'
        'exit "${MOCK_INSPECTION_RC:-3}"\n',
    )
    write_executable(bin_dir / "az", AZ_STUB)

    env = dict(os.environ)
    env.update({
        "HOME": str(root),
        "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
        "MOCK_REMOTE": str(remote_file),
        "MOCK_LOG": str(log_file),
        "MOCK_SUB": SUB,
        "MOCK_ROLE": ROLE,
        "MOCK_VAULT": VAULT,
        "MOCK_ASSIGNMENT": assignment,
        "MOCK_PRINCIPAL": principal,
        "MOCK_VM_ID": vm_id,
        "MOCK_PREFLIGHT": "allow",
        "MOCK_INSPECTION_RC": "3",
    })

    def reset(status="prepared", records=None):
        state_file.write_text(json.dumps({
            **base_state, "status": status,
        }))
        state_file.chmod(0o600)
        remote_file.write_text(json.dumps(
            [] if records is None else records
        ))
        log_file.write_text("")

    def run(mode, confirmation=""):
        return subprocess.run(
            ["bash", str(controller), mode],
            input=confirmation,
            text=True,
            capture_output=True,
            env=env,
        )

    def status():
        return json.loads(state_file.read_text())["status"]

    def writes():
        return log_file.read_text().splitlines()

    print("[1/7] New grant")
    reset()
    result = run("grant")
    assert result.returncode == 0, result.stdout + result.stderr
    assert status() == "granted"
    assert writes() == ["CREATE"]
    assert len(json.loads(remote_file.read_text())) == 1
    print("PASS: Role created and grant persisted")

    print("[2/7] Repeat grant")
    result = run("grant")
    assert result.returncode == 0, result.stdout + result.stderr
    assert writes() == ["CREATE"]
    print("PASS: Existing grant reused without another CREATE")

    print("[3/7] Cleanup")
    result = run("cleanup", "REMOVE\n")
    assert result.returncode == 0, result.stdout + result.stderr
    assert status() == "removed"
    assert json.loads(remote_file.read_text()) == []
    assert writes() == ["CREATE", "DELETE"]
    print("PASS: Role removed and cleanup persisted")

    print("[4/7] Repeat cleanup")
    result = run("cleanup")
    assert result.returncode == 0, result.stdout + result.stderr
    assert writes() == ["CREATE", "DELETE"]
    print("PASS: Cleanup is idempotent")

    print("[5/7] Reject grant after removed")
    result = run("grant")
    assert result.returncode != 0
    assert writes() == ["CREATE", "DELETE"]
    print("PASS: Completed recovery cannot grant again")

    print("[6/7] Reject wrong principal")
    reset(records=[{
        "id": assignment,
        "scope": VAULT,
        "principalId": str(uuid.uuid4()),
        "roleDefinitionId": ROLE,
    }])
    result = run("cleanup", "REMOVE\n")
    assert result.returncode != 0
    assert writes() == []
    print("PASS: Identity mismatch prevents DELETE")

    print("[7/7] Reject grant on failed recovery preflight")
    reset()
    env["MOCK_PREFLIGHT"] = "reject"
    result = run("grant")
    assert result.returncode != 0
    assert writes() == []
    assert status() == "prepared"
    print("PASS: Failed preflight prevents CREATE")

print("PASS: All RBAC lifecycle integration tests completed")
