#!/usr/bin/env python3
"""Offline validation of the LearningSteps Key Vault network snapshot."""

import argparse
import ipaddress
import json
import os
import stat
from pathlib import Path

SUB = "901cb597-1248-4bc6-8b92-0452114c48b9"
RG = "rg-learningsteps-devsecops"
VAULT = "kv-lsteps-305c3ba6"
PE = "pe-learningsteps-keyvault"
VNET = "vnet-learningsteps-weu"
SUBNET = "snet-private-endpoints"
ZONE = "privatelink.vaultcore.azure.net"

BASE = f"/subscriptions/{SUB}/resourceGroups/{RG}"
VAULT_ID = f"{BASE}/providers/Microsoft.KeyVault/vaults/{VAULT}"
PE_ID = f"{BASE}/providers/Microsoft.Network/privateEndpoints/{PE}"
VNET_ID = f"{BASE}/providers/Microsoft.Network/virtualNetworks/{VNET}"
SUBNET_ID = f"{VNET_ID}/subnets/{SUBNET}"
ZONE_ID = f"{BASE}/providers/Microsoft.Network/privateDnsZones/{ZONE}"
FQDN = f"{VAULT}.{ZONE}."


def require(condition, message):
    if not condition:
        raise ValueError(message)


def same(a, b):
    return isinstance(a, str) and a.casefold() == b.casefold()


def resource_id(item):
    return item.get("id") if isinstance(item, dict) else None


def load_snapshot(path):
    info = path.lstat()

    require(stat.S_ISREG(info.st_mode), "Snapshot is not a regular file")
    require(info.st_uid == os.getuid(), "Unexpected snapshot owner")
    require(info.st_mode & 0o077 == 0, "Snapshot permissions too broad")

    return json.loads(path.read_text())


def validate(data):
    require(same(data["subscription"], SUB), "Wrong subscription")

    vault = data["vault"]
    endpoint = data["endpoint"]
    nic = data["nic"]
    record = data["record"]

    require(same(resource_id(vault), VAULT_ID), "Wrong Key Vault ID")
    require(same(vault.get("name"), VAULT), "Wrong Key Vault name")
    require(same(resource_id(endpoint), PE_ID), "Wrong endpoint ID")
    require(same(endpoint.get("name"), PE), "Wrong endpoint name")

    connections = (
        endpoint.get("privateLinkServiceConnections") or []
    )
    require(len(connections) == 1, "Expected one endpoint connection")

    conn = connections[0]
    require(
        same(conn.get("privateLinkServiceId"), VAULT_ID),
        "Endpoint targets wrong resource",
    )
    require(conn.get("groupIds") == ["vault"], "Wrong endpoint group")
    require(
        conn.get("privateLinkServiceConnectionState", {}).get("status")
        == "Approved",
        "Endpoint connection not Approved",
    )

    require(
        same(resource_id(endpoint.get("subnet")), SUBNET_ID),
        "Unexpected endpoint subnet",
    )

    interfaces = endpoint.get("networkInterfaces") or []
    require(len(interfaces) == 1, "Expected one endpoint NIC")
    require(
        same(resource_id(interfaces[0]), resource_id(nic)),
        "Endpoint NIC identity mismatch",
    )

    configurations = nic.get("ipConfigurations") or []
    require(len(configurations) == 1, "Expected one NIC IP configuration")
    config = configurations[0]

    require(
        same(resource_id(config.get("subnet")), SUBNET_ID),
        "Unexpected NIC subnet",
    )

    ip_text = config.get("privateIPAddress")
    ip = ipaddress.IPv4Address(ip_text)

    private_ranges = [
        ipaddress.IPv4Network("10.0.0.0/8"),
        ipaddress.IPv4Network("172.16.0.0/12"),
        ipaddress.IPv4Network("192.168.0.0/16"),
    ]
    require(
        any(ip in network for network in private_ranges),
        "Endpoint IP is not RFC1918",
    )

    groups = data["zone_groups"]
    require(len(groups) == 1, "Expected one DNS zone group")

    zones = groups[0].get("privateDnsZoneConfigs") or []
    require(len(zones) == 1, "Expected one DNS zone config")
    require(
        same(zones[0].get("privateDnsZoneId"), ZONE_ID),
        "Wrong private DNS zone",
    )

    require(same(record.get("fqdn"), FQDN), "Wrong DNS record name")

    addresses = record.get("aRecords") or []
    require(len(addresses) == 1, "Expected one DNS A record")
    require(
        addresses[0].get("ipv4Address") == str(ip),
        "DNS IP differs from endpoint NIC IP",
    )

    links = data["links"]
    matching = [
        link for link in links
        if same(
            resource_id(link.get("virtualNetwork")),
            VNET_ID,
        )
    ]
    require(len(matching) == 1, "Expected one matching VNet link")
    require(
        matching[0].get("virtualNetworkLinkState") == "Completed",
        "VNet link not completed",
    )

    return str(ip)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    args = parser.parse_args()

    try:
        data = load_snapshot(args.snapshot)
        address = validate(data)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, f"REJECT: {exc}\n")

    print(address)


if __name__ == "__main__":
    main()
