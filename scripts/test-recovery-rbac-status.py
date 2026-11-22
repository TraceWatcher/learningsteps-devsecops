#!/usr/bin/env python3

import json
import os
import pathlib
import subprocess
import tempfile
import uuid

ROOT = pathlib.Path(__file__).resolve().parents[1]
CONTROLLER = ROOT / "scripts/recovery-keyvault-rbac.sh"

SUB = "901cb597-1248-4bc6-8b92-0452114c48b9"
VAULT = (
    f"/subscriptions/{SUB}"
    "/resourceGroups/rg-learningsteps-devsecops"
    "/providers/Microsoft.KeyVault/vaults/kv-lsteps-305c3ba6"
)
ROLE_ID = (
    f"/subscriptions/{SUB}"
    "/providers/Microsoft.Authorization/roleDefinitions/"
    "00000000-0000-0000-0000-000000000001"
)
ASSIGNMENT = (
    VAULT
    + "/providers/Microsoft.Authorization/roleAssignments/"
    + str(uuid.uuid4())
)
PRINCIPAL = str(uuid.uuid4())

with tempfile.TemporaryDirectory() as temp:
    root = pathlib.Path(temp)
    bin_dir = root / "bin"
    bin_dir.mkdir()

    # Stub Azure CLI: only read operations are supported.
    az = bin_dir / "az"
    az.write_text("""#!/usr/bin/env python3
import json
import os
import sys

args = sys.argv[1:]

if args[:2] == ["account", "show"]:
    print(os.environ["TEST_SUBSCRIPTION"])
elif args[:3] == ["role", "definition", "list"]:
    print(os.environ["TEST_ROLE_ID"])
elif args[:3] == ["role", "assignment", "list"]:
    if os.environ["TEST_PRESENT"] == "1":
        print(json.dumps([{
            "id": os.environ["TEST_ASSIGNMENT"],
            "principalId": os.environ["TEST_PRINCIPAL"],
            "scope": os.environ["TEST_VAULT"],
            "roleDefinitionId": os.environ["TEST_ROLE_ID"],
        }]))
    else:
        print("[]")
else:
    print("ERROR: Unexpected Azure command", file=sys.stderr)
    sys.exit(99)
""")
    az.chmod(0o700)

    state_dir = root / "learningsteps-recovery"
    state_dir.mkdir(mode=0o700)
    state_file = state_dir / "temporary-keyvault-rbac.json"

    base_state = {
        "recovery_id": str(uuid.uuid4()),
        "assignment_id": ASSIGNMENT,
        "vault_id": VAULT,
        "principal_id": PRINCIPAL,
        "vm_id": str(uuid.uuid4()),
        "role": "Key Vault Secrets Officer",
    }

    env = dict(os.environ)
    env.update({
        "HOME": str(root),
        "PATH": str(bin_dir) + ":" + os.environ["PATH"],
        "TEST_SUBSCRIPTION": SUB,
        "TEST_ROLE_ID": ROLE_ID,
        "TEST_ASSIGNMENT": ASSIGNMENT,
        "TEST_PRINCIPAL": PRINCIPAL,
        "TEST_VAULT": VAULT,
    })

    cases = [
        ("prepared", False, 0, "No Azure assignment"),
        ("prepared", True, 3, "RECONCILE"),
        ("granted", True, 0, "states agree"),
        ("granted", False, 3, "RECONCILE"),
        ("removed", False, 0, "states agree"),
        ("removed", True, 1, "ERROR"),
    ]

    for status, present, expected_rc, expected_text in cases:
        state = {**base_state, "status": status}
        state_file.write_text(json.dumps(state))
        state_file.chmod(0o600)

        env["TEST_PRESENT"] = "1" if present else "0"

        result = subprocess.run(
            ["bash", str(CONTROLLER), "status"],
            env=env,
            capture_output=True,
            text=True,
        )

        output = result.stdout + result.stderr

        assert result.returncode == expected_rc, (
            status, present, result.returncode, output
        )
        assert expected_text in output, (
            status, present, output
        )

        print(
            f"PASS: local={status}, azure="
            f"{'present' if present else 'absent'}"
        )

print("PASS: All RBAC status integration tests completed")
