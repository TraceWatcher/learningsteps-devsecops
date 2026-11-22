#!/usr/bin/env python3

import pathlib
import subprocess
import tempfile

SOURCE = pathlib.Path(
    "scripts/recovery-keyvault-rbac.sh"
).read_text()

start_marker = 'matches = ['
end_marker = '\nPY\nMATCH_RC=$?'

start = SOURCE.index(start_marker)
end = SOURCE.index(end_marker, start)

CHECK_CODE = SOURCE[start:end]

with tempfile.TemporaryDirectory() as temp:
    test_file = pathlib.Path(temp) / "check.py"
    test_file.write_text(
        "import json\nimport os\n" + CHECK_CODE + "\n"
    )

    import json
    import os

    vault = (
        "/subscriptions/00000000-0000-0000-0000-000000000000"
        "/resourceGroups/test"
        "/providers/Microsoft.KeyVault/vaults/test"
    )

    role = (
        "/subscriptions/00000000-0000-0000-0000-000000000000"
        "/providers/Microsoft.Authorization/roleDefinitions/"
        "00000000-0000-0000-0000-000000000001"
    )

    assignment = (
        vault
        + "/providers/Microsoft.Authorization/roleAssignments/"
        + "00000000-0000-0000-0000-000000000002"
    )

    base = {
        "id": assignment,
        "scope": vault,
        "principalId": "correct-principal",
        "roleDefinitionId": role,
    }

    def check(records):
        env = dict(os.environ)
        env.update({
            "ASSIGNMENTS": json.dumps(records),
            "ASSIGNMENT_ID": assignment,
            "PRINCIPAL_ID": "correct-principal",
            "VAULT_ID": vault,
            "ROLE_ID": role,
        })

        return subprocess.run(
            ["python3", str(test_file)],
            env=env,
            capture_output=True,
            text=True,
        ).returncode

    assert check([]) == 0
    print("PASS: Missing assignment detected")

    assert check([base]) == 10
    print("PASS: Matching assignment accepted")

    assert check([
        {**base, "principalId": "wrong-principal"}
    ]) == 20
    print("PASS: Wrong principal rejected")

    assert check([
        {**base, "roleDefinitionId": "wrong-role"}
    ]) == 20
    print("PASS: Wrong role rejected")

    assert check([
        {**base, "scope": "/wrong/scope"}
    ]) == 20
    print("PASS: Wrong scope rejected")

print("PASS: All RBAC validation tests completed")
