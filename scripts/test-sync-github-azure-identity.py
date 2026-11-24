#!/usr/bin/env python3
"""Offline tests for the post-provisioning identity sync, using strict CLI stubs."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import quote

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
from urllib.parse import quote

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
        self.set_cmd = SET_CMD
        self.get_cmd = GET_CMD
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
        self.assertEqual(calls.count(self.set_cmd), int(writes))
        self.assertEqual(calls.count(self.get_cmd), int(readback))
        if readback:
            self.assertEqual(calls[-2:], [self.set_cmd, self.get_cmd])
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

    def setup_operations(self):
        environment = "production-operations"
        identity = "id-learningsteps-github-operations"
        postgres = "psql-learningsteps-operations"
        role = "LearningSteps Environment Operator"
        path = f"{REPO_PATH}/environments/{environment}"
        self.ops_environment_cmd = github(path)
        self.ops_branch_cmd = github(f"{path}/deployment-branch-policies?per_page=100")
        self.ops_list_cmd = github(f"{path}/variables?per_page=100", "--paginate")
        role_filter = quote(f"roleName eq '{role}'", safe="")
        role_url = (
            f"https://management.azure.com{RG_ID}/providers/Microsoft.Authorization/roleDefinitions"
            f"?api-version=2022-04-01&$filter={role_filter}"
        )
        self.ops_role_cmd = [*az("rest", "--method", "get", "--url", role_url), "-o", "json"]
        assignment_args = [
            *az("role", "assignment", "list"),
            "--assignee-object-id",
            PRINCIPAL,
            "--include-groups",
            "--fill-principal-name",
            "false",
            "--fill-role-definition-name",
            "false",
            "-o",
            "json",
        ]
        self.ops_assignments_cmd = [*assignment_args, "--all"]
        self.ops_ancestors_cmd = [
            *assignment_args,
            "--scope",
            f"/subscriptions/{SUB}",
            "--include-inherited",
        ]
        self.ops_fic_cmd = [identity if arg == IDENTITY else arg for arg in FIC_CMD]
        self.set_cmd = [environment if arg == "production" else arg for arg in SET_CMD]
        self.get_cmd = github(f"{path}/variables/AZURE_CLIENT_ID")

        # Remove release-specific responses so that a call to a release resource fails the test.
        for command in (
            IDENTITY_CMD,
            FIC_CMD,
            LIST_CMD,
            ROLE_CMD,
            show("acr", ACR),
            show("aks", AKS),
            assignments(ACR_ID),
            assignments(AKS_ID),
        ):
            self.responses.pop(json.dumps(command))
        self.respond(
            show("identity", identity),
            {
                "id": f"{RG_ID}/providers/Microsoft.ManagedIdentity/userAssignedIdentities/{identity}",
                "clientId": CURRENT,
                "tenantId": TENANT,
                "principalId": PRINCIPAL,
            },
        )
        self.ops_environment = {
            "name": environment,
            "id": 28365573053,
            "can_admins_bypass": False,
            "deployment_branch_policy": {
                "protected_branches": False,
                "custom_branch_policies": True,
            },
            "protection_rules": [
                {
                    "type": "required_reviewers",
                    "prevent_self_review": False,
                    "reviewers": [
                        {"type": "User", "reviewer": {"id": 292215891, "login": "TraceWatcher"}}
                    ],
                },
                {"type": "branch_policy"},
            ],
        }
        self.respond(self.ops_environment_cmd, self.ops_environment)
        self.respond(
            self.ops_branch_cmd,
            {"total_count": 1, "branch_policies": [{"name": "main", "type": "branch"}]},
        )
        self.ops_vars = [
            {"name": "AZURE_CLIENT_ID", "value": CURRENT},
            {"name": "AZURE_TENANT_ID", "value": TENANT},
            {"name": "AZURE_SUBSCRIPTION_ID", "value": SUB},
            {"name": "POSTGRES_SERVER_NAME", "value": postgres},
        ]
        self.respond(self.ops_list_cmd, {"total_count": 4, "variables": self.ops_vars})

        self.ops_fic = {
            **self.fic,
            "name": f"fic-learningsteps-github-{environment}",
            "subject": f"{self.fic['subject']}-operations",
        }
        self.respond(self.ops_fic_cmd, [self.ops_fic])
        self.ops_role = {
            "roleName": role,
            "type": "CustomRole",
            "assignableScopes": [RG_ID],
            "permissions": [
                {
                    "actions": [
                        f"{CLUSTER}/read",
                        f"{CLUSTER}/start/action",
                        f"{CLUSTER}/stop/action",
                        "Microsoft.DBforPostgreSQL/flexibleServers/read",
                        "Microsoft.DBforPostgreSQL/flexibleServers/start/action",
                        "Microsoft.DBforPostgreSQL/flexibleServers/stop/action",
                        "Microsoft.Compute/virtualMachines/instanceView/read",
                        "Microsoft.Compute/virtualMachines/deallocate/action",
                    ],
                    "notActions": [],
                    "dataActions": [],
                    "notDataActions": [],
                }
            ],
        }
        self.ops_assignments = [
            assignment(scope, CUSTOM_ROLE)
            for scope in (
                AKS_ID,
                f"{RG_ID}/providers/Microsoft.DBforPostgreSQL/flexibleServers/{postgres}",
                f"{RG_ID}/providers/Microsoft.Compute/virtualMachines/learningsteps-maintenance",
            )
        ]
        self.ops_role_id = self.ops_assignments[0]["roleDefinitionId"]
        self.respond_operations_role()
        self.respond(self.ops_assignments_cmd, self.ops_assignments)
        self.respond(self.ops_ancestors_cmd, [])

    def respond_operations_role(self):
        self.respond(
            self.ops_role_cmd,
            {"value": [{"id": self.ops_role_id, "name": CUSTOM_ROLE, "properties": self.ops_role}]},
        )

    def test_operations_check_and_update_only_operations_variables(self):
        self.setup_operations()
        self.assert_sync(0, "bereits aktuell", args=("--check", "--operations"))
        self.ops_vars[0]["value"] = FORMER
        self.respond(self.ops_list_cmd, {"total_count": 4, "variables": self.ops_vars})
        self.assert_sync(1, "aktualisiert werden", args=("--operations", "--check"))
        self.respond(self.set_cmd, raw="")
        self.respond(self.get_cmd, {"name": "AZURE_CLIENT_ID", "value": CURRENT})
        self.assert_sync(
            0, "aktualisiert und verifiziert", args=("--operations",), writes=True, readback=True
        )

    def test_operations_rejects_missing_environment_or_protection(self):
        self.setup_operations()
        self.respond(self.ops_environment_cmd, status=1)
        self.assert_sync(2, "manuell angelegt", args=("--operations",))
        reviewer_rule, branch_rule = self.ops_environment["protection_rules"]
        for rules in (
            [],
            [reviewer_rule],
            [branch_rule],
            [reviewer_rule, reviewer_rule, branch_rule],
        ):
            with self.subTest(rules=rules):
                self.respond(
                    self.ops_environment_cmd, {**self.ops_environment, "protection_rules": rules}
                )
                self.assert_sync(1, "Reviewer-Regel", args=("--operations",))
        self.respond(self.ops_environment_cmd, self.ops_environment)
        main = {"name": "main", "type": "branch"}
        for policies in (
            [],
            [{"name": "main", "type": "tag"}],
            [{"name": "*", "type": "branch"}],
            [main, {"name": "develop", "type": "branch"}],
            [main, {"name": "v*", "type": "tag"}],
        ):
            with self.subTest(policies=policies):
                self.respond(
                    self.ops_branch_cmd, {"total_count": len(policies), "branch_policies": policies}
                )
                self.assert_sync(1, "genau eine Branch-Regel für main", args=("--operations",))

    def test_operations_fails_closed_when_reviewer_settings_differ(self):
        self.setup_operations()
        reviewer_rule, branch_rule = self.ops_environment["protection_rules"]
        reviewer = reviewer_rule["reviewers"][0]
        other = {"type": "User", "reviewer": {"id": 73, "login": "another-user"}}
        for overrides in (
            {"prevent_self_review": True},
            {"prevent_self_review": None},
            {"reviewers": []},
            {"reviewers": [{**reviewer, "type": "Team"}]},
            {"reviewers": [{**reviewer, "reviewer": {**reviewer["reviewer"], "id": 73}}]},
            {"reviewers": [{**reviewer, "reviewer": {**reviewer["reviewer"], "login": "renamed"}}]},
            {"reviewers": [reviewer, other]},
        ):
            with self.subTest(overrides=overrides):
                self.respond(
                    self.ops_environment_cmd,
                    {
                        **self.ops_environment,
                        "protection_rules": [{**reviewer_rule, **overrides}, branch_rule],
                    },
                )
                self.assert_sync(1, "Reviewer-Regel", args=("--operations",))

    def test_operations_requires_explicitly_disabled_administrator_bypass(self):
        self.setup_operations()
        self.ops_environment["can_admins_bypass"] = True
        self.respond(self.ops_environment_cmd, self.ops_environment)
        self.assert_sync(1, "Administrator-Bypass", args=("--operations",))
        self.ops_environment.pop("can_admins_bypass")
        self.respond(self.ops_environment_cmd, self.ops_environment)
        self.assert_sync(1, "Administrator-Bypass", args=("--operations",))

    def test_operations_rejects_wrong_or_additional_federation(self):
        self.setup_operations()
        for fics in ([{**self.ops_fic, "subject": self.fic["subject"]}], [self.ops_fic, self.fic]):
            self.respond(self.ops_fic_cmd, fics)
            self.assert_sync(
                1, "Federated Credential für production-operations", args=("--operations",)
            )

    def test_operations_validates_target_tenant_and_subscription(self):
        self.setup_operations()
        for index in (1, 2):
            with self.subTest(variable=self.ops_vars[index]["name"]):
                original = self.ops_vars[index]["value"]
                self.ops_vars[index]["value"] = FORMER
                self.respond(self.ops_list_cmd, {"total_count": 4, "variables": self.ops_vars})
                self.assert_sync(1, self.ops_vars[index]["name"], args=("--operations",))
                self.ops_vars[index]["value"] = original

    def test_operations_rejects_role_expansion(self):
        self.setup_operations()
        self.ops_role["permissions"][0]["actions"].append("Microsoft.Compute/virtualMachines/*")
        self.respond_operations_role()
        self.assert_sync(1, "Aktionen oder AssignableScopes", args=("--operations",))
        self.ops_role["permissions"][0]["actions"].pop()
        self.ops_role["assignableScopes"].append(f"/subscriptions/{SUB}")
        self.respond_operations_role()
        self.assert_sync(1, "Aktionen oder AssignableScopes", args=("--operations",))

    def test_operations_requires_only_the_three_direct_assignments(self):
        self.setup_operations()
        for assignments_ in (
            self.ops_assignments[:2],
            [*self.ops_assignments, assignment(RG_ID, CUSTOM_ROLE)],
            [*self.ops_assignments, assignment(ACR_ID, ACR_PUSH)],
            [*self.ops_assignments[:2], {**self.ops_assignments[2], "principalId": FORMER}],
        ):
            with self.subTest(assignments=assignments_):
                self.respond(self.ops_assignments_cmd, assignments_)
                self.assert_sync(1, "exakt drei direkte", args=("--operations", "--check"))
        self.respond(self.ops_assignments_cmd, self.ops_assignments)
        self.respond(
            self.ops_ancestors_cmd,
            [assignment("/providers/Microsoft.Management/managementGroups/parent", CUSTOM_ROLE)],
        )
        self.assert_sync(1, "übergeordnetem Scope", args=("--operations", "--check"))

    def test_operations_rejects_wrong_assignment_role_or_subscription(self):
        self.setup_operations()
        for role_id in (
            self.ops_role_id.replace(SUB, FORMER),
            self.ops_role_id.replace(CUSTOM_ROLE, ACR_PUSH),
        ):
            with self.subTest(role_id=role_id):
                altered = {**self.ops_assignments[0], "roleDefinitionId": role_id}
                self.respond(self.ops_assignments_cmd, [altered, *self.ops_assignments[1:]])
                self.assert_sync(1, "exakt drei direkte", args=("--operations", "--check"))

    def test_operations_rejects_definition_id_in_wrong_subscription(self):
        self.setup_operations()
        self.ops_role_id = self.ops_role_id.replace(SUB, FORMER)
        self.respond_operations_role()
        self.assert_sync(1, "unerwartete ARM-ID", args=("--operations", "--check"))

    def test_operations_accepts_qualified_group_definition_and_subscription_assignment(self):
        self.setup_operations()
        self.ops_role_id = (
            f"{RG_ID}/providers/Microsoft.Authorization/roleDefinitions/{CUSTOM_ROLE}"
        )
        self.respond_operations_role()
        group_assignment = {**self.ops_assignments[0], "roleDefinitionId": self.ops_role_id.upper()}
        self.respond(self.ops_assignments_cmd, [group_assignment, *self.ops_assignments[1:]])
        self.assert_sync(0, "bereits aktuell", args=("--operations", "--check"))


if __name__ == "__main__":
    unittest.main()
