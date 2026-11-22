#!/usr/bin/env python3
"""Validate an Azure VM Run Command result without printing output."""

import argparse
import json
import pathlib
import re
import sys

MARKERS = {
    "install": "__LS_INSTALL_RC__",
    "restore": "__LS_RESTORE_RC__",
}


def verify(result, operation):
    entries = result.get("value")

    if not isinstance(entries, list) or len(entries) != 1:
        raise ValueError("Unexpected Azure response structure")

    entry = entries[0]

    if entry.get("code") != "ProvisioningState/succeeded":
        raise ValueError("Azure Run Command did not succeed")

    message = entry.get("message")

    if not isinstance(message, str):
        raise ValueError("Missing Run Command output")

    if message.count("[stdout]") != 1:
        raise ValueError("Invalid stdout section")

    if message.count("[stderr]") != 1:
        raise ValueError("Invalid stderr section")

    stdout = message.split("[stdout]", 1)[1].split(
        "[stderr]", 1
    )[0]

    stderr = message.split("[stderr]", 1)[1]

    # Refuse truncated, duplicated or conflicting status markers.
    marker = MARKERS[operation]
    matches = re.findall(
        rf"^{re.escape(marker)}=([0-9]+)$",
        stdout,
        flags=re.MULTILINE,
    )

    if len(matches) != 1:
        raise ValueError("Missing or duplicate exit marker")

    if stdout.strip().splitlines()[-1] != (
        f"{marker}={matches[0]}"
    ):
        raise ValueError("Exit marker is not final output")

    if stderr.strip():
        raise ValueError("Remote command reported stderr output")

    if int(matches[0]) != 0:
        raise ValueError("Remote script failed")

    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--operation",
        choices=MARKERS,
        required=True,
    )
    parser.add_argument("--result", required=True)
    args = parser.parse_args()

    path = pathlib.Path(args.result)

    if not path.is_file() or path.is_symlink():
        raise ValueError("Invalid result file")

    result = json.loads(path.read_text(encoding="utf-8"))

    verify(result, args.operation)

    print(f"PASS: {args.operation} Run Command verified")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        print(
            "ERROR: Run Command verification failed",
            file=sys.stderr,
        )
        sys.exit(1)
