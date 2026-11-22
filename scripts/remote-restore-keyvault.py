#!/usr/bin/env python3
"""Guarded Key Vault restore on a dedicated recovery VM."""

import argparse
import importlib.util
import ipaddress
import json
import os
import pathlib
import stat
import sys
import urllib.request
import uuid

RECOVERY_DIR = pathlib.Path("/var/lib/learningsteps-recovery")
REMOTE_MODULE = pathlib.Path(
    "/opt/learningsteps-recovery/restore-keyvault-secret.py"
)


def verify_file(path, mode):
    info = path.lstat()

    if not stat.S_ISREG(info.st_mode):
        raise RuntimeError("Unsafe recovery file type")

    if info.st_uid != 0 or stat.S_IMODE(info.st_mode) != mode:
        raise RuntimeError("Unsafe recovery file ownership or permissions")

    if info.st_nlink != 1 or info.st_size == 0:
        raise RuntimeError("Unsafe or empty recovery file")


def verify_local_files():
    directory = RECOVERY_DIR.lstat()

    if (
        not stat.S_ISDIR(directory.st_mode)
        or directory.st_uid != 0
        or stat.S_IMODE(directory.st_mode) != 0o700
    ):
        raise RuntimeError("Unsafe recovery directory")

    identity = RECOVERY_DIR / "recipient-identity.txt"
    encrypted = RECOVERY_DIR / "postgres-admin-password.age"

    verify_file(identity, 0o600)
    verify_file(encrypted, 0o600)

    return identity, encrypted


def verify_vm_identity(expected_vm_id):
    url = (
        "http://169.254.169.254/metadata/instance"
        "?api-version=2021-02-01"
    )

    request = urllib.request.Request(
        url, headers={"Metadata": "true"}
    )

    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({})
    )

    with opener.open(request, timeout=10) as response:
        metadata = json.load(response)

    actual = metadata["compute"]["vmId"]

    if uuid.UUID(actual) != uuid.UUID(expected_vm_id):
        raise RuntimeError("Recovery VM identity mismatch")

    print("PASS: Recovery VM identity verified")


def verify_module_directory():
    directory = REMOTE_MODULE.parent
    info = directory.lstat()

    if not stat.S_ISDIR(info.st_mode):
        raise RuntimeError("Unsafe restore module directory")

    if info.st_uid != 0:
        raise RuntimeError("Restore module directory must belong to root")

    if stat.S_IMODE(info.st_mode) != 0o700:
        raise RuntimeError(
            "Restore module directory permissions must be 0700"
        )


def load_restore_module():
    verify_module_directory()
    verify_file(REMOTE_MODULE, 0o600)

    spec = importlib.util.spec_from_file_location(
        "learningsteps_kv_restore", REMOTE_MODULE
    )

    if spec is None or spec.loader is None:
        raise RuntimeError("Restore module unavailable")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--vault", required=True)
    parser.add_argument("--private-ip", required=True)
    parser.add_argument("--expected-vm-id", required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    if not args.execute:
        print("DRY RUN: Remote restore disabled")
        return 0

    if os.geteuid() != 0:
        raise RuntimeError("Remote restore requires root")

    if not args.vault.isascii() or not all(
        c.islower() or c.isdigit() or c == "-"
        for c in args.vault
    ):
        raise RuntimeError("Invalid vault name")

    ipaddress.IPv4Address(args.private_ip)
    uuid.UUID(args.expected_vm_id)

    verify_vm_identity(args.expected_vm_id)

    identity, encrypted = verify_local_files()
    module = load_restore_module()

    module.verify_private_endpoint(
        args.vault, args.private_ip
    )

    token = module.get_identity_token()

    secret_url = (
        f"https://{args.vault}.vault.azure.net/"
        "secrets/postgres-admin-password"
        "?api-version=7.4"
    )

    # restore_missing_secret() performs another private DNS
    # check, requires an HTTP 404 before PUT, and verifies
    # the exact returned secret version and password.
    return module.restore_missing_secret(
        secret_url,
        token,
        str(identity),
        str(encrypted),
        args.vault,
        args.private_ip,
    )


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(
            f"ERROR: Remote restore failed "
            f"({type(exc).__name__})",
            file=sys.stderr,
        )
        sys.exit(1)
