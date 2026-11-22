#!/usr/bin/env python3

import argparse
import hmac
import json
import subprocess
import sys
import urllib.error
import urllib.request


def request_json(url, token, method="GET", payload=None):
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=body,
        headers=headers,
        method=method,
    )

    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({})
    )

    with opener.open(request, timeout=20) as response:
        return json.load(response)


def get_identity_token():
    url = (
        "http://169.254.169.254/metadata/identity/oauth2/token"
        "?api-version=2018-02-01"
        "&resource=https%3A%2F%2Fvault.azure.net"
    )

    request = urllib.request.Request(
        url,
        headers={"Metadata": "true"},
    )

    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({})
    )

    with opener.open(request, timeout=20) as response:
        return json.load(response)["access_token"]



def restore_missing_secret(url, token, identity, encrypted_password):
    """Restore after externally authorized target and RBAC checks.

    Not exposed through the command-line restore guard.
    """
    result = subprocess.run(
        [
            "age", "--decrypt",
            "--identity", identity,
            encrypted_password,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )

    password = result.stdout

    if not password or b"\\x00" in password:
        raise RuntimeError("Invalid recovery password")

    password_text = password.decode("utf-8")

    print("RESTORE: Writing missing Key Vault secret")

    request_json(
        url,
        token,
        method="PUT",
        payload={
            "value": password_text,
            "attributes": {"enabled": True},
        },
    )

    print("VERIFY: Reading restored secret")

    verified = request_json(url, token)

    value = verified.get("value")
    enabled = verified.get("attributes", {}).get("enabled")

    if enabled is not True or not isinstance(value, str):
        raise RuntimeError("Restored secret is not readable and enabled")

    if not hmac.compare_digest(
        password, value.encode("utf-8")
    ):
        raise RuntimeError("Restored secret value mismatch")

    print("PASS: Restored secret matches encrypted backup")
    return 0


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument("--vault", required=True)
    parser.add_argument("--identity", required=True)
    parser.add_argument("--encrypted-password", required=True)
    parser.add_argument("--restore", action="store_true")

    args = parser.parse_args()

    if args.restore:
        raise RuntimeError(
            "Direct secret restoration is disabled. "
            "Use the guarded recovery controller."
        )

    print("[1/4] Authenticating with Managed Identity")
    token = get_identity_token()

    print("[2/4] Checking existing secret")

    url = (
        f"https://{args.vault}.vault.azure.net/"
        "secrets/postgres-admin-password?api-version=7.4"
    )

    try:
        data = request_json(url, token)
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise RuntimeError(
                f"Secret check failed: HTTP {exc.code}"
            ) from None
    else:
        value = data.get("value")
        enabled = data.get("attributes", {}).get("enabled")

        if enabled is not True:
            raise RuntimeError("Existing secret is disabled")

        if not isinstance(value, str) or not value:
            raise RuntimeError("Existing secret is empty")

        print("PRESENT: Secret exists, enabled and readable")
        print("STOP: Existing secret will not be overwritten")
        return 0

    print("MISSING: Secret not found")

    if not args.restore:
        print("DRY RUN: No secret will be created")
        return 3

    return restore_missing_secret(
        url, token, args.identity, args.encrypted_password
    )

if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(
            f"ERROR: {type(exc).__name__}: "
            "Key Vault restoration failed",
            file=sys.stderr,
        )
        sys.exit(1)
