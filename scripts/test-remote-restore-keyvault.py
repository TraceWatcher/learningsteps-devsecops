#!/usr/bin/env python3
"""Local tests for the guarded remote restore entrypoint."""

import importlib.util
import pathlib
from unittest.mock import patch

SCRIPT = (
    pathlib.Path(__file__).resolve().parent
    / "remote-restore-keyvault.py"
)

spec = importlib.util.spec_from_file_location(
    "remote_restore", SCRIPT
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

VAULT = "kv-lsteps-305c3ba6"
PRIVATE_IP = "10.30.3.4"
VM_ID = "11111111-1111-4111-8111-111111111111"


def test_success():
    calls = []

    class FakeRestore:
        @staticmethod
        def verify_private_endpoint(vault, private_ip):
            calls.append("dns")
            assert vault == VAULT
            assert private_ip == PRIVATE_IP

        @staticmethod
        def get_identity_token():
            calls.append("token")
            return "mock-token"

        @staticmethod
        def restore_missing_secret(
            url, token, identity, encrypted, vault, private_ip
        ):
            calls.append("restore")
            assert token == "mock-token"
            assert vault == VAULT
            assert private_ip == PRIVATE_IP
            assert "postgres-admin-password" in url
            return 0

    with patch.object(module.os, "geteuid", return_value=0), \
         patch.object(module, "verify_vm_identity") as vm_check, \
         patch.object(
             module,
             "verify_local_files",
             return_value=(
                 pathlib.Path("/mock/identity"),
                 pathlib.Path("/mock/password.age"),
             ),
         ) as file_check, \
         patch.object(
             module,
             "load_restore_module",
             return_value=FakeRestore,
         ), \
         patch(
             "sys.argv",
             [
                 "remote-restore-keyvault.py",
                 "--vault", VAULT,
                 "--private-ip", PRIVATE_IP,
                 "--expected-vm-id", VM_ID,
                 "--execute",
             ],
         ):

        assert module.main() == 0

    vm_check.assert_called_once_with(VM_ID)
    file_check.assert_called_once()
    assert calls == ["dns", "token", "restore"]
    print("PASS: Guarded restore execution order")


def test_wrong_vm():
    with patch.object(module.os, "geteuid", return_value=0), \
         patch.object(
             module,
             "verify_vm_identity",
             side_effect=RuntimeError("Wrong VM"),
         ), \
         patch.object(module, "verify_local_files") as files, \
         patch(
             "sys.argv",
             [
                 "remote-restore-keyvault.py",
                 "--vault", VAULT,
                 "--private-ip", PRIVATE_IP,
                 "--expected-vm-id", VM_ID,
                 "--execute",
             ],
         ):

        try:
            module.main()
        except RuntimeError:
            pass
        else:
            raise AssertionError("Wrong VM accepted")

        files.assert_not_called()

    print("PASS: Wrong VM blocks restore")


test_success()
test_wrong_vm()

print("PASS: Remote restore entrypoint tests completed")
