#!/usr/bin/env python3
"""Positive and negative offline tests for the Key Vault network validator."""

import copy
import importlib.util
import json
import pathlib
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent
SNAPSHOT = (
    pathlib.Path.home()
    / "learningsteps-recovery/keyvault-network-snapshot.json"
)

spec = importlib.util.spec_from_file_location(
    "network_validator",
    ROOT / "validate-keyvault-network.py",
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

original = json.loads(SNAPSHOT.read_text())


def test(name, modify=None, accepted=False):
    data = copy.deepcopy(original)

    if modify is not None:
        modify(data)

    try:
        result = mod.validate(data)
    except (ValueError, KeyError, TypeError):
        if accepted:
            raise AssertionError(f"{name}: unexpectedly rejected")
        print(f"PASS: {name} rejected")
    else:
        if not accepted:
            raise AssertionError(f"{name}: unexpectedly accepted")
        print(f"PASS: {name} accepted, IP={result}")


test("Original snapshot", accepted=True)

test(
    "Wrong subscription",
    lambda d: d.update(subscription="00000000-0000-0000-0000-000000000000"),
)

test(
    "Wrong Vault",
    lambda d: d["vault"].update(id="invalid-vault-id"),
)

test(
    "Wrong endpoint target",
    lambda d: d["endpoint"]["privateLinkServiceConnections"][0].update(
        privateLinkServiceId="invalid-target"
    ),
)

test(
    "Connection rejected",
    lambda d: d["endpoint"]["privateLinkServiceConnections"][0][
        "privateLinkServiceConnectionState"
    ].update(status="Rejected"),
)

test(
    "Wrong endpoint NIC",
    lambda d: d["nic"].update(id="invalid-nic-id"),
)

test(
    "Wrong subnet",
    lambda d: d["nic"]["ipConfigurations"][0]["subnet"].update(
        id="invalid-subnet"
    ),
)

test(
    "Public endpoint IP",
    lambda d: d["nic"]["ipConfigurations"][0].update(
        privateIPAddress="8.8.8.8"
    ),
)

test(
    "Wrong DNS IP",
    lambda d: d["record"]["aRecords"][0].update(
        ipv4Address="10.30.3.99"
    ),
)

test(
    "Wrong DNS zone",
    lambda d: d["zone_groups"][0]["privateDnsZoneConfigs"][0].update(
        privateDnsZoneId="invalid-zone"
    ),
)

test(
    "VNet link disconnected",
    lambda d: d["links"][0].update(
        virtualNetworkLinkState="Disconnected"
    ),
)

print("PASS: All network validation scenarios completed")
