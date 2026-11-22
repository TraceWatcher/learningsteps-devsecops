#!/usr/bin/env python3

import argparse
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

    print("[3/4] Decrypting recovery password")

    result = subprocess.run(
        [
            "age",
            "--decrypt",
            "--identity",
            args.identity,
            args.encrypted_password,
        ],
        capture_output=True,
        check=True,
    )

    password = result.stdout

    if not password or b"\x00" in password:
        raise RuntimeError("Invalid recovered password")

    # PostgreSQL password must be valid UTF-8.
    password_text = password.decode("utf-8")

    print("[4/4] Creating Key Vault secret")

    request_json(
        url,
        token,
        method="PUT",
        payload={
            "value": password_text,
            "attributes": {"enabled": True},
        },
    )

    print("PASS: Key Vault secret created")
    print("PASS: No password or token printed")
    return 0


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
