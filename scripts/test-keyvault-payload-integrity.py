#!/usr/bin/env python3
"""Offline integrity tests for generated recovery payloads."""

import importlib.util
import os
import pathlib
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent

spec = importlib.util.spec_from_file_location(
    "payload_verifier",
    ROOT / "verify-keyvault-payload.py",
)
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


with tempfile.TemporaryDirectory() as tmp:
    directory = pathlib.Path(tmp) / "payloads"
    directory.mkdir(mode=0o700)

    payload = directory / "install.sh"
    original = verifier.expected_install()

    def write(data):
        payload.write_bytes(data)
        payload.chmod(0o600)

    def rejected(name, operation="install", path=None):
        try:
            verifier.verify(operation, path or payload)
        except (OSError, ValueError):
            print(f"PASS: {name} rejected")
        else:
            raise AssertionError(f"SECURITY FAILURE: {name} accepted")

    write(original)

    size = verifier.verify("install", payload)
    assert size == len(original)
    print("PASS: Original installation payload accepted")

    write(original + b"\necho UNAUTHORIZED\n")
    rejected("Manipulated shell payload")

    write(original)
    rejected("Installation used as restore", operation="restore")

    payload.chmod(0o666)
    rejected("World-writable payload")

    payload.unlink()
    external = pathlib.Path(tmp) / "external.sh"
    external.write_bytes(original)
    external.chmod(0o600)
    payload.symlink_to(external)
    rejected("Symlink payload")

    payload.unlink()
    write(original)

    directory.chmod(0o777)
    rejected("Unsafe payload directory")

print("PASS: All six payload integrity scenarios completed")
