#!/usr/bin/env python3

import argparse
import ipaddress
import json
import socket
import sys
import urllib.error
import urllib.request


def fetch_json(url, headers):
    request = urllib.request.Request(url, headers=headers)

    # Do not route Azure IMDS or private Key Vault
    # requests through environment-configured proxies.
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({})
    )

    with opener.open(request, timeout=20) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--vault", required=True)
    parser.add_argument("--private-ip", required=True)
    parser.add_argument(
        "--secret",
        default="postgres-admin-password"
    )
    args = parser.parse_args()

    hostname = f"{args.vault}.vault.azure.net"

    print("[1/3] Checking private DNS")

    expected_ip = ipaddress.IPv4Address(args.private_ip)

    resolved = {
        ipaddress.IPv4Address(item[4][0])
        for item in socket.getaddrinfo(
            hostname, 443, family=socket.AF_INET
        )
    }

    if resolved != {expected_ip}:
        raise RuntimeError(
            "DNS does not resolve exclusively "
            "to the expected private endpoint"
        )

    print("PASS: Private DNS verified")

    print("[2/3] Authenticating with Managed Identity")

    imds_url = (
        "http://169.254.169.254/metadata/identity/oauth2/token"
        "?api-version=2018-02-01"
        "&resource=https%3A%2F%2Fvault.azure.net"
    )

    identity = fetch_json(
        imds_url,
        {"Metadata": "true"}
    )

    token = identity["access_token"]

    if not token:
        raise RuntimeError("Managed Identity token missing")

    print("PASS: Managed Identity authentication")

    print("[3/3] Inspecting Key Vault secret")

    secret_url = (
        f"https://{hostname}/secrets/{args.secret}"
        "?api-version=7.4"
    )

    try:
        data = fetch_json(
            secret_url,
            {"Authorization": f"Bearer {token}"}
        )

    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            print("MISSING: Secret was not found")
            return 3
        raise RuntimeError(
            f"Key Vault request returned HTTP {exc.code}"
        ) from None

    if data.get("attributes", {}).get("enabled") is not True:
        raise RuntimeError("Secret is disabled")

    value = data.get("value")

    if not isinstance(value, str) or not value:
        raise RuntimeError("Secret value missing or empty")

    print("PASS: Secret exists, is enabled and is readable")
    print("PASS: No token or secret value printed")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(
            f"ERROR: {type(exc).__name__}: "
            "Secret inspection failed",
            file=sys.stderr
        )
        sys.exit(1)
