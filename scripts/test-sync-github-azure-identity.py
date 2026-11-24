#!/usr/bin/env python3
"""Offline tests for the post-provisioning identity sync, using strict CLI stubs."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("sync-github-azure-identity.sh")
SUB = "11111111-1111-4111-8111-111111111111"
TENANT = "22222222-2222-4222-8222-222222222222"
PRINCIPAL = "33333333-3333-4333-8333-333333333333"
CURRENT = "44444444-4444-4444-8444-44444444444a"
FORMER = "55555555-5555-4555-8555-555555555555"
CUSTOM_ROLE = "66666666-6666-4666-8666-666666666666"
ACR_PUSH = "8311e382-0749-4cb8-b61a-304f252e45ec"
RG = "rg-learningsteps-devsecops"
IDENTITY = "id-learningsteps-github"
ACR = "acrlearningstepsbff17e9a"
AKS = "aks-learningsteps"
AKS_ROLE = "LearningSteps AKS Command Deployer"
REPO = "TraceWatcher/learningsteps-devsecops"
REPO_PATH = f"repos/{REPO}"
VARS = f"{REPO_PATH}/environments/production/variables"
RG_ID = f"/subscriptions/{SUB}/resourceGroups/{RG}"
ACR_ID = f"{RG_ID}/providers/Microsoft.ContainerRegistry/registries/{ACR}"
AKS_ID = f"{RG_ID}/providers/Microsoft.ContainerService/managedClusters/{AKS}"
CLUSTER = "Microsoft.ContainerService/managedClusters"
ACTIONS = [f"{CLUSTER}/{suffix}" for suffix in ("read", "runCommand/action", "commandResults/read")]
SECRET_MARKER = "synthetic-token-must-not-appear-in-output"

STUB = r"""
import json
import os
import sys
from pathlib import Path

root = Path(os.environ["SYNC_TEST_ROOT"])
command = [Path(sys.argv[0]).name, *sys.argv[1:]]
key = json.dumps(command)
with (root / "calls").open("a") as log:
    print(key, file=log)
expected = json.loads((root / "responses").read_text())
if key not in expected:
    (root / "unexpected").write_text(key)
    sys.exit(99)
status, output = expected[key]
if status:
    print(os.environ["SYNC_TEST_SECRET"], file=sys.stderr)
    sys.exit(status)
sys.stdout.write(output)
"""


def az(*args, scoped=True):
    subscription = ["--subscription", SUB] if scoped else []
    return ["az", *args, *subscription]


def show(resource, name):
    return [*az(resource, "show"), "--resource-group", RG, "--name", name, "-o", "json"]


def github(endpoint, *args):
    return ["gh", "api", "--hostname", "github.com", "--method", "GET", endpoint, *args]


def assignments(scope):
    return [
        *az("role", "assignment", "list"),
        "--scope",
        scope,
        "--include-inherited",
        "--assignee-object-id",
        PRINCIPAL,
        "--fill-principal-name",
        "false",
        "--fill-role-definition-name",
        "false",
        "-o",
        "json",
    ]


def assignment(scope, role, principal=PRINCIPAL, condition=None):
    return {
        "scope": scope,
        "roleDefinitionId": f"/subscriptions/{SUB}/providers/Microsoft.Authorization/roleDefinitions/{role}",
        "principalId": principal,
        "condition": condition,
    }


def permissions(actions, exclusions=()):
    return {"actions": list(actions), "notActions": list(exclusions)}


ACCOUNT_CMD = [*az("account", "show", scoped=False), "-o", "json"]
IDENTITY_CMD = show("identity", IDENTITY)
REPO_CMD = github(REPO_PATH)
OIDC_CMD = github(
    f"{REPO_PATH}/actions/oidc/customization/sub", "-H", "X-GitHub-Api-Version: 2026-03-10"
)
FIC_CMD = [
    *az("identity", "federated-credential", "list"),
    "--resource-group",
    RG,
    "--identity-name",
    IDENTITY,
    "-o",
    "json",
]
ROLE_CMD = [*az("role", "definition", "list"), "--scope", RG_ID, "--name", AKS_ROLE, "-o", "json"]
LIST_CMD = github(f"{VARS}?per_page=100", "--paginate")
GET_CMD = github(f"{VARS}/AZURE_CLIENT_ID")
SET_CMD = [
    "gh",
    "variable",
    "set",
    "AZURE_CLIENT_ID",
    "--repo",
    f"github.com/{REPO}",
    "--env",
    "production",
    "--body",
    CURRENT,
]


class IdentitySyncTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        for name in ("az", "gh"):
            stub = self.root / name
            stub.write_text(f"#!{sys.executable}\n{STUB}")
            stub.chmod(0o700)

        self.responses = {}
        self.respond(ACCOUNT_CMD, {"id": SUB, "tenantId": TENANT})
        self.respond(
            IDENTITY_CMD,
            {
                "id": f"{RG_ID}/providers/Microsoft.ManagedIdentity/userAssignedIdentities/{IDENTITY}",
                "clientId": CURRENT,
                "tenantId": TENANT,
                "principalId": PRINCIPAL,
            },
        )
        self.respond(
            REPO_CMD,
            {
                "id": 1460727418,
                "name": "learningsteps-devsecops",
                "owner": {"id": 292215891, "login": "TraceWatcher"},
                "created_at": "2026-11-17T00:00:00Z",
            },
        )
        self.respond(OIDC_CMD, {"use_default": True})
        self.fic = {
            "name": "fic-learningsteps-github-production",
            "issuer": "https://token.actions.githubusercontent.com",
            "subject": "repo:TraceWatcher@292215891/learningsteps-devsecops@1460727418:environment:production",
            "audiences": ["api://AzureADTokenExchange"],
        }
        self.respond(FIC_CMD, [self.fic])
        self.respond(
            show("acr", ACR), {"id": ACR_ID, "roleAssignmentMode": "LegacyRegistryPermissions"}
        )
        self.respond(show("aks", AKS), {"id": AKS_ID})
        self.role(permissions(ACTIONS))
        self.respond(assignments(ACR_ID), [assignment(ACR_ID.upper(), ACR_PUSH.upper())])
        self.respond(assignments(AKS_ID), [assignment(AKS_ID, CUSTOM_ROLE)])
        self.variables()

    def respond(self, command, payload=None, *, status=0, raw=None):
        self.responses[json.dumps(command)] = (status, json.dumps(payload) if raw is None else raw)

    def variables(self, client=CURRENT, tenant=TENANT, subscription=SUB):
        variables = [
            {"name": "AZURE_TENANT_ID", "value": tenant},
            {"name": "AZURE_SUBSCRIPTION_ID", "value": subscription},
        ]
        if client is not None:
            variables.append({"name": "AZURE_CLIENT_ID", "value": client})
        self.respond(LIST_CMD, {"total_count": len(variables), "variables": variables})
        return variables

    def role(self, *blocks):
        self.respond(
            ROLE_CMD,
            [
                {
                    "name": CUSTOM_ROLE,
                    "roleName": AKS_ROLE,
                    "roleType": "CustomRole",
                    "permissions": list(blocks),
                }
            ],
        )

    def allow_write(self, value=CURRENT):
        self.respond(SET_CMD, raw="")
        self.respond(GET_CMD, {"name": "AZURE_CLIENT_ID", "value": value})

    def assert_sync(self, code, message, *, args=(), writes=False, readback=False):
        (self.root / "responses").write_text(json.dumps(self.responses))
        log = self.root / "calls"
        log.write_text("")
        result = subprocess.run(
            ["bash", str(SCRIPT), *args],
            env={
                "PATH": os.pathsep.join((str(self.root), os.defpath)),
                "SYNC_TEST_ROOT": str(self.root),
                "SYNC_TEST_SECRET": SECRET_MARKER,
            },
            capture_output=True,
            text=True,
            timeout=10,
        )
        unexpected = self.root / "unexpected"
        self.assertFalse(unexpected.exists(), unexpected.read_text() if unexpected.exists() else "")
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, code, output)
        self.assertIn(message, output)
        self.assertNotIn(SECRET_MARKER, output)
        calls = [json.loads(line) for line in log.read_text().splitlines()]
        self.assertEqual(calls.count(SET_CMD), int(writes))
        self.assertEqual(calls.count(GET_CMD), int(readback))
        if readback:
            self.assertEqual(calls[-2:], [SET_CMD, GET_CMD])
        return output

    def test_up_to_date_and_case_insensitive(self):
        self.variables(client=CURRENT.upper())
        self.assert_sync(0, "bereits aktuell")
        self.assert_sync(0, "bereits aktuell", args=("--check",))

    def test_stale_and_missing_client_id_with_readback(self):
        self.allow_write()
        for client in (FORMER, None):
            with self.subTest(client=client):
                self.variables(client=client)
                self.assert_sync(0, "aktualisiert und verifiziert", writes=True, readback=True)

    def test_check_only_reports_stale_or_missing_client_id(self):
        for client in (FORMER, None, CURRENT + "\n"):
            with self.subTest(client=client):
                self.variables(client=client)
                self.assert_sync(1, "muss aktualisiert werden", args=("--check",))

    def test_paginated_variables_are_read_across_pages(self):
        variables = self.variables()
        pages = [{"total_count": 3, "variables": page} for page in (variables[:1], variables[1:])]
        self.respond(LIST_CMD, raw="\n".join(map(json.dumps, pages)))
        self.assert_sync(0, "bereits aktuell", args=("--check",))

    def test_wrong_tenant_or_subscription(self):
        self.variables(tenant=FORMER)
        self.assert_sync(1, "AZURE_TENANT_ID fehlt oder weicht ab")
        self.variables(subscription=FORMER)
        self.assert_sync(1, "AZURE_SUBSCRIPTION_ID fehlt oder weicht ab")

    def test_missing_principal_is_a_technical_error(self):
        self.respond(IDENTITY_CMD, {"clientId": CURRENT, "tenantId": TENANT})
        self.assert_sync(2, "Managed Identity ist ungültig oder unvollständig", args=("--check",))

    def test_fic_must_match_issuer_audience_name_and_exact_subject(self):
        for key, wrong in (
            ("name", "wrong-credential"),
            ("issuer", "https://wrong.example"),
            ("subject", f"repo:{REPO}:environment:production"),
            ("audiences", ["wrong"]),
        ):
            with self.subTest(key=key):
                self.respond(FIC_CMD, [{**self.fic, key: wrong}])
                self.assert_sync(1, "Federated Credential für production fehlt oder weicht")

    def test_incompatible_oidc_settings(self):
        self.respond(OIDC_CMD, {"use_default": True, "use_immutable_subject": False})
        self.assert_sync(1, "ID-basierte GitHub-OIDC-Subject")
        self.respond(
            OIDC_CMD, {"use_default": False, "include_claim_keys": ["repo", "job_workflow_ref"]}
        )
        self.assert_sync(1, "OIDC-Template")

    def test_older_repo_requires_explicit_immutable_setting(self):
        repo = json.loads(self.responses[json.dumps(REPO_CMD)][1])
        self.respond(REPO_CMD, {**repo, "created_at": "2026-07-01T00:00:00Z"})
        self.assert_sync(2, "ID-basierte GitHub-OIDC-Subject", args=("--check",))
        self.respond(
            OIDC_CMD,
            {
                "use_default": False,
                "include_claim_keys": ["repo", "context"],
                "use_immutable_subject": True,
            },
        )
        self.assert_sync(0, "bereits aktuell", args=("--check",))

    def test_custom_role_wildcards_case_and_permission_blocks(self):
        self.role(
            permissions([f"{CLUSTER.upper()}/*"], [f"{CLUSTER}/runCommand/*"]),
            permissions([ACTIONS[1]]),
        )
        self.assert_sync(0, "bereits aktuell", args=("--check",))

    def test_role_missing_or_excluding_required_actions(self):
        for block, action in (
            (permissions(ACTIONS[:-1]), ACTIONS[2]),
            (permissions(["*"], [ACTIONS[1].upper()]), ACTIONS[1]),
            (permissions([f"{CLUSTER}/*"], [f"{CLUSTER}/commandResults/*"]), ACTIONS[2]),
        ):
            with self.subTest(block=block):
                self.role(block)
                self.assert_sync(1, f"erlaubt {action} nicht")

    def test_inherited_role_is_reported_as_scope_drift(self):
        self.respond(assignments(ACR_ID), [assignment(RG_ID, ACR_PUSH)])
        self.respond(assignments(AKS_ID), [assignment(f"/subscriptions/{SUB}", CUSTOM_ROLE)])
        output = self.assert_sync(
            1, "AcrPush ist als geerbte Zuweisung sichtbar", args=("--check",)
        )
        self.assertIn(f"{AKS_ROLE} ist als geerbte Zuweisung sichtbar", output)
        self.assertIn("fehlt als unbedingte direkte Zuweisung", output)

    def test_acr_abac_mode_does_not_honor_acrpush(self):
        self.respond(
            show("acr", ACR), {"id": ACR_ID, "roleAssignmentMode": "AbacRepositoryPermissions"}
        )
        self.assert_sync(1, "ACR-Rollenzuweisungsmodus")

    def test_unexpected_assignments_do_not_satisfy_direct_requirement(self):
        self.respond(
            assignments(ACR_ID),
            [
                assignment(ACR_ID, ACR_PUSH, principal=FORMER),
                assignment(ACR_ID, CUSTOM_ROLE),
                assignment(f"{ACR_ID}/child", ACR_PUSH),
                assignment(ACR_ID, ACR_PUSH, condition="an explicit condition"),
                assignment(f"{RG_ID}/different-resource", ACR_PUSH),
                assignment(RG_ID, CUSTOM_ROLE),
            ],
        )
        output = self.assert_sync(1, "andere oder bedingte geerbte Zuweisungen sichtbar")
        self.assertIn("AcrPush fehlt als unbedingte direkte Zuweisung", output)
        self.assertNotIn("AcrPush ist als geerbte Zuweisung sichtbar", output)

    def test_api_errors_are_technical_and_do_not_leak_output(self):
        for cmd in (ACCOUNT_CMD, LIST_CMD, FIC_CMD, OIDC_CMD, ROLE_CMD, assignments(ACR_ID)):
            with self.subTest(cmd=cmd):
                key = json.dumps(cmd)
                saved = self.responses[key]
                self.respond(cmd, status=33)
                self.assert_sync(2, "fehlgeschlagen", args=("--check",))
                self.responses[key] = saved

    def test_incomplete_pagination_and_malformed_role_assignment(self):
        self.respond(LIST_CMD, {"total_count": 2, "variables": []})
        self.assert_sync(2, "Variablen ist ungültig oder unvollständig")
        self.variables()
        self.respond(assignments(AKS_ID), [{"scope": AKS_ID, "principalId": PRINCIPAL}])
        self.assert_sync(2, "Rollenzuweisungen ist ungültig oder unvollständig")
        self.respond(
            assignments(AKS_ID),
            [{**assignment(AKS_ID, CUSTOM_ROLE), "roleDefinitionId": CUSTOM_ROLE}],
        )
        self.assert_sync(2, "Rollenzuweisungen ist ungültig oder unvollständig")

    def test_write_error_stops_before_readback(self):
        self.variables(client=FORMER)
        self.respond(SET_CMD, status=3)
        self.assert_sync(2, "konnte nicht bestätigt geschrieben werden", writes=True)

    def test_wrong_readback_values_or_api_error_fail_sync(self):
        self.variables(client=FORMER)
        self.allow_write(value=FORMER)
        self.assert_sync(2, "Rücklesewert", writes=True, readback=True)
        self.respond(GET_CMD, {"name": "AZURE_CLIENT_ID"})
        self.assert_sync(2, "GitHub-Rückleseantwort", writes=True, readback=True)
        self.respond(GET_CMD, {"name": "AZURE_CLIENT_ID", "value": CURRENT + "\n"})
        self.assert_sync(2, "GitHub-Rückleseantwort", writes=True, readback=True)
        self.respond(GET_CMD, status=4)
        self.assert_sync(2, "Rücklesen", writes=True, readback=True)


if __name__ == "__main__":
    unittest.main()
