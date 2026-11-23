#!/usr/bin/env python3
"""Offline verification of generated LearningSteps recovery payloads."""

import argparse
import hmac
import importlib.util
import os
import stat
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def load_module(name):
    path = ROOT / name
    spec = importlib.util.spec_from_file_location(
        name.replace("-", "_").replace(".py", ""), path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def expected_install():
    generator = load_module("build-keyvault-install-payload.py")
    body = generator.build_payload()
    return (
        "set +e\n"
        "(\n"
        + body
        + "\n)\n"
        "rc=$?\n"
        'printf \'__LS_INSTALL_RC__=%s\\n\' "$rc"\n'
        "exit 0\n"
    ).encode("utf-8")


def expected_restore(state, snapshot):
    generator = load_module("build-keyvault-restore-payload.py")
    network = load_module("validate-keyvault-network.py")

    vm_id = generator.load_state(state)
    ip = network.validate(network.load_snapshot(snapshot))

    return generator.build_payload(vm_id, ip).encode("utf-8")


def verify(mode, payload, state=None, snapshot=None, verified_output=None):
    expected_name = {
        "install": "install.sh",
        "restore": "restore.sh",
    }[mode]

    if not payload.is_absolute() or payload.name != expected_name:
        raise ValueError("Unexpected payload path or operation")

    parent = payload.parent
    parent_info = parent.lstat()

    if (
        parent.name != "payloads"
        or not stat.S_ISDIR(parent_info.st_mode)
        or parent_info.st_uid != os.getuid()
        or stat.S_IMODE(parent_info.st_mode) != 0o700
    ):
        raise ValueError("Unsafe payload directory")

    # Open without following a final-component symlink.
    fd = os.open(payload, os.O_RDONLY | os.O_NOFOLLOW)

    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())

        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_size > 500_000
        ):
            raise ValueError("Unsafe payload file")

        actual = stream.read()

    if mode == "install":
        expected = expected_install()
    else:
        if state is None or snapshot is None:
            raise ValueError("Restore requires state and network snapshot")
        expected = expected_restore(state, snapshot)


    if not hmac.compare_digest(actual, expected):
        raise ValueError("Payload differs from trusted generator output")

    if verified_output is not None:
        if not verified_output.is_absolute():
            raise ValueError("Verified output must be an absolute path")

        directory_info = verified_output.parent.lstat()

        if (
            not stat.S_ISDIR(directory_info.st_mode)
            or directory_info.st_uid != os.getuid()
            or stat.S_IMODE(directory_info.st_mode) != 0o700
        ):
            raise ValueError("Unsafe verified-output directory")

        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
        fd = os.open(verified_output, flags, 0o600)

        try:
            with os.fdopen(fd, "wb") as stream:
                os.fchmod(stream.fileno(), 0o600)
                stream.write(actual)
                stream.flush()
                os.fsync(stream.fileno())
        except BaseException:
            verified_output.unlink(missing_ok=True)
            raise

    return len(actual)



def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["install", "restore"],
                        required=True)
    parser.add_argument("--payload", type=Path, required=True)
    parser.add_argument("--state", type=Path)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--verified-output", type=Path)
    args = parser.parse_args()

    try:
        size = verify(
            args.mode,
            args.payload,
            args.state,
            args.snapshot,
            args.verified_output,
        )
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        parser.exit(1, f"REJECT: {exc}\n")

    print(f"PASS: {args.mode} payload verified ({size} bytes)")


if __name__ == "__main__":
    main()
