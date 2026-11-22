#!/usr/bin/env python3

import importlib.util
import pathlib
import socket
from unittest.mock import patch

path = pathlib.Path("scripts/restore-keyvault-secret.py")
spec = importlib.util.spec_from_file_location("kv_restore", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

vault = "test-vault"
private_ip = "10.30.3.4"


def dns_response(ip):
    return [
        (
            socket.AF_INET,
            socket.SOCK_STREAM,
            6,
            "",
            (ip, 443),
        )
    ]


print("[1/3] Correct private endpoint")

with patch.object(
    module.socket,
    "getaddrinfo",
    return_value=dns_response(private_ip),
):
    module.verify_private_endpoint(vault, private_ip)

print("PASS: Expected private endpoint accepted")

print("[2/3] Wrong private endpoint")

with patch.object(
    module.socket,
    "getaddrinfo",
    return_value=dns_response("10.30.3.99"),
):
    try:
        module.verify_private_endpoint(vault, private_ip)
    except RuntimeError:
        print("PASS: Incorrect private endpoint rejected")
    else:
        raise AssertionError("Wrong endpoint accepted")

print("[3/3] Public IP rejected")

with patch.object(
    module.socket,
    "getaddrinfo",
    return_value=dns_response("20.20.20.20"),
):
    try:
        module.verify_private_endpoint(vault, "20.20.20.20")
    except RuntimeError:
        print("PASS: Public endpoint rejected")
    else:
        raise AssertionError("Public endpoint accepted")

print("PASS: All private DNS tests completed")
