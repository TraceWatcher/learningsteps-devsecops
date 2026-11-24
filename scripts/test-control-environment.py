#!/usr/bin/env python3
"""Offline tests for operations protection and the Azure state transitions."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
SUB = "11111111-1111-4111-8111-111111111111"
RG = "rg-learningsteps-devsecops"
AKS = "aks-learningsteps"
POSTGRES = "psql-learningsteps-operations"
VM = "learningsteps-maintenance"
REPO = "TraceWatcher/learningsteps-devsecops"
ENVIRONMENT_PATH = f"repos/{REPO}/environments/production-operations"
VM_URL = (
    f"https://management.azure.com/subscriptions/{SUB}/resourceGroups/{RG}"
    f"/providers/Microsoft.Compute/virtualMachines/{VM}/instanceView?api-version=2025-11-01"
)
CLI = """
import json
import os
import sys
from pathlib import Path

queue = Path(os.environ["CLI_QUEUE"])
pending = json.loads(queue.read_text())
command = [Path(sys.argv[0]).name, *sys.argv[1:]]
if not pending or pending[0][0] != command:
    print(f"Unexpected command: {command}", file=sys.stderr)
    sys.exit(98)
_, status, output = pending.pop(0)
queue.write_text(json.dumps(pending))
if status:
    print("AuthorizationFailed (stub)", file=sys.stderr)
else:
    sys.stdout.write(output + "\\n")
sys.exit(status)
"""


def az(*args):
    return ["az", *args, "--subscription", SUB]


def get_aks(power, provisioning="Succeeded", *, status=0):
    return (
        az(
            "aks",
            "show",
            "-g",
            RG,
            "-n",
            AKS,
            "--query",
            "{power:powerState.code,provisioning:provisioningState}",
            "-o",
            "json",
        ),
        status,
        json.dumps({"power": power, "provisioning": provisioning}),
    )


def get_pg(state, *, status=0):
    return (
        az(
            "postgres",
            "flexible-server",
            "show",
            "-g",
            RG,
            "-n",
            POSTGRES,
            "--query",
            "state",
            "-o",
            "tsv",
        ),
        status,
        state,
    )


def get_vm(state, *, status=0):
    return (
        az(
            "rest",
            "--method",
            "get",
            "--url",
            VM_URL,
            "--query",
            "statuses[?starts_with(code, 'PowerState/')].code | [0]",
            "-o",
            "tsv",
        ),
        status,
        f"PowerState/{state}" if state else "",
    )


def change(resource, state, name, *, status=0):
    return (az(*resource, state, "-g", RG, "-n", name, "--no-wait", "-o", "none"), status, "")


def github(path, payload):
    return (
        ["gh", "api", "--hostname", "github.com", "--method", "GET", path],
        0,
        json.dumps(payload),
    )


class OperationsTest(unittest.TestCase):
    def run_script(self, queue, command, **env):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("az", "gh"):
                stub = root / name
                stub.write_text(f"#!{sys.executable}\n{CLI}")
                stub.chmod(0o700)
            pending = root / "queue"
            pending.write_text(json.dumps(queue))
            result = subprocess.run(
                ["bash", str(SCRIPTS / command[0]), *command[1:]],
                env={
                    "PATH": os.pathsep.join((str(root), os.defpath)),
                    "CLI_QUEUE": str(pending),
                    **env,
                },
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertNotIn("Unexpected command", result.stderr)
            self.assertEqual(json.loads(pending.read_text()), [], result.stderr)
            return result

    def run_operation(self, action, *queue, confirm="STOP", poll_timeout="10", poll_interval="0"):
        return self.run_script(
            queue,
            ["control-environment.sh"],
            ACTION=action,
            RG=RG,
            AKS=AKS,
            POSTGRES=POSTGRES,
            VM=VM,
            AZURE_SUBSCRIPTION_ID=SUB,
            CONFIRM_STOP=confirm,
            POLL_TIMEOUT_SECONDS=poll_timeout,
            POLL_INTERVAL_SECONDS=poll_interval,
        )

    def test_status_reads_only_resource_endpoints(self):
        result = self.run_operation(
            "status", get_aks("Running"), get_pg("Ready"), get_vm("running")
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PowerState/running", result.stdout)

    def test_start_waits_for_postgres_and_for_aks_provisioning(self):
        result = self.run_operation(
            "start",
            get_aks("Stopped"),
            get_pg("Stopped"),
            get_vm("deallocated"),
            change(("postgres", "flexible-server"), "start", POSTGRES),
            get_pg("Starting"),
            get_pg("Ready"),
            change(("aks",), "start", AKS),
            get_aks("Running", provisioning="Starting"),
            get_aks("Running"),
            get_aks("Running"),
            get_pg("Ready"),
            get_vm("deallocated"),
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_stop_waits_for_each_resource_before_continue(self):
        result = self.run_operation(
            "stop",
            get_aks("Running"),
            get_pg("Ready"),
            get_vm("running"),
            change(("aks",), "stop", AKS),
            get_aks("Running", provisioning="Stopping"),
            get_aks("Stopped"),
            change(("postgres", "flexible-server"), "stop", POSTGRES),
            get_pg("Stopping"),
            get_pg("Stopped"),
            change(("vm",), "deallocate", VM),
            get_vm("deallocating"),
            get_vm("deallocated"),
            get_aks("Stopped"),
            get_pg("Stopped"),
            get_vm("deallocated"),
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_stop_can_resume_vm_deallocation_without_resubmitting(self):
        result = self.run_operation(
            "stop",
            get_aks("Stopped"),
            get_pg("Stopped"),
            get_vm("deallocating"),
            get_vm("deallocated"),
            get_aks("Stopped"),
            get_pg("Stopped"),
            get_vm("deallocated"),
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_stop_requires_confirmation_before_any_calls(self):
        result = self.run_operation("stop", confirm="stop")
        self.assertEqual(result.returncode, 1)
        self.assertIn("STOP bestätigt", result.stderr)

    def test_instance_view_error_or_empty_state_blocks_mutation(self):
        for state in (get_vm("running", status=1), get_vm("")):
            with self.subTest(state=state):
                result = self.run_operation("stop", get_aks("Running"), get_pg("Ready"), state)
                self.assertEqual(result.returncode, 1)
                self.assertIn("Statusabfrage für vm_state", result.stderr)

    def test_failed_azure_submission_is_not_polled(self):
        result = self.run_operation(
            "start",
            get_aks("Stopped"),
            get_pg("Stopped"),
            get_vm("deallocated"),
            change(("postgres", "flexible-server"), "start", POSTGRES, status=1),
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("AuthorizationFailed", result.stderr)
        self.assertIn(
            "Azure-Operation für pg_state auf Ready fehlgeschlagen (Exit-Code 1)", result.stderr
        )

    def test_failed_poll_aborts_before_next_mutation(self):
        result = self.run_operation(
            "stop",
            get_aks("Running"),
            get_pg("Ready"),
            get_vm("running"),
            change(("aks",), "stop", AKS),
            get_aks("Running", status=1),
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("AuthorizationFailed", result.stderr)
        self.assertIn("Statusabfrage für aks_state fehlgeschlagen", result.stderr)

    def test_postgres_poll_authorization_failure_prevents_vm_deallocation(self):
        result = self.run_operation(
            "stop",
            get_aks("Stopped"),
            get_pg("Ready"),
            get_vm("running"),
            change(("postgres", "flexible-server"), "stop", POSTGRES),
            get_pg("Stopping"),
            get_pg("Stopping", status=1),
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("AuthorizationFailed", result.stderr)
        self.assertIn("Statusabfrage für pg_state fehlgeschlagen", result.stderr)

    def test_failed_provisioning_is_not_reported_as_target_state(self):
        result = self.run_operation(
            "start",
            get_aks("Stopped"),
            get_pg("Ready"),
            get_vm("running"),
            change(("aks",), "start", AKS),
            get_aks("Running", provisioning="Failed"),
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("unerwarteten Status Failed beim Warten auf Running", result.stderr)

    def test_aks_stop_rejects_starting(self):
        result = self.run_operation(
            "stop",
            get_aks("Running"),
            get_pg("Ready"),
            get_vm("running"),
            change(("aks",), "stop", AKS),
            get_aks("Running", provisioning="Starting"),
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("unerwarteten Status Starting beim Warten auf Stopped", result.stderr)

    def test_postgres_start_rejects_disabled_or_regression(self):
        for states, failure in (
            (["Disabled"], "Disabled"),
            (["Stopped", "Starting", "Stopped"], "Stopped"),
        ):
            with self.subTest(states=states):
                result = self.run_operation(
                    "start",
                    get_aks("Stopped"),
                    get_pg("Stopped"),
                    get_vm("running"),
                    change(("postgres", "flexible-server"), "start", POSTGRES),
                    *(get_pg(state) for state in states),
                )
                self.assertEqual(result.returncode, 1)
                self.assertIn(f"unerwarteten Status {failure} beim Warten auf Ready", result.stderr)

    def test_vm_deallocation_rejects_regression_after_forward_progress(self):
        result = self.run_operation(
            "stop",
            get_aks("Stopped"),
            get_pg("Stopped"),
            get_vm("running"),
            change(("vm",), "deallocate", VM),
            get_vm("stopping"),
            get_vm("stopped"),
            get_vm("deallocating"),
            get_vm("running"),
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn(
            "unerwarteten Status PowerState/running beim Warten auf PowerState/deallocated",
            result.stderr,
        )

    def test_timeout_blocks_following_operations(self):
        result = self.run_operation(
            "start",
            get_aks("Stopped"),
            get_pg("Stopped"),
            get_vm("deallocated"),
            change(("postgres", "flexible-server"), "start", POSTGRES),
            get_pg("Starting"),
            poll_timeout="1",
            poll_interval="1",
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("Timeout für pg_state", result.stderr)

    def test_stop_timeout_prevents_postgres_stop_and_vm_deallocation(self):
        result = self.run_operation(
            "stop",
            get_aks("Running"),
            get_pg("Ready"),
            get_vm("running"),
            change(("aks",), "stop", AKS),
            get_aks("Running", provisioning="Stopping"),
            poll_timeout="1",
            poll_interval="1",
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("Timeout für aks_state", result.stderr)

    def test_environment_id_must_match_before_branches_are_queried(self):
        protected = {
            "id": 28365573053,
            "name": "production-operations",
            "can_admins_bypass": False,
            "deployment_branch_policy": {
                "protected_branches": False,
                "custom_branch_policies": True,
            },
            "protection_rules": [
                {"type": "branch_policy"},
                {
                    "type": "required_reviewers",
                    "prevent_self_review": False,
                    "reviewers": [
                        {"type": "User", "reviewer": {"id": 292215891, "login": "TraceWatcher"}}
                    ],
                },
            ],
        }
        environment_lookup = github(ENVIRONMENT_PATH, protected)
        result = self.run_script(
            [environment_lookup], ["check-operations-environment.sh", REPO, "28365573054"]
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("Environment-ID", result.stderr)
        result = self.run_script(
            [
                environment_lookup,
                github(
                    f"{ENVIRONMENT_PATH}/deployment-branch-policies?per_page=100",
                    {
                        "total_count": 1,
                        "branch_policies": [{"name": "main", "type": "branch"}],
                    },
                ),
            ],
            ["check-operations-environment.sh", REPO, "28365573053"],
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "28365573053")


if __name__ == "__main__":
    unittest.main()
