#!/usr/bin/env python3

import base64
import hashlib
import os
import pathlib
import re
import subprocess
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts/transport-keyvault-password.sh"


def run(*args):
    return subprocess.run(
        args,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def encrypt(recipient, plaintext, destination):
    subprocess.run(
        ["age", "-r", recipient, "-o", str(destination)],
        input=plaintext,
        check=True,
        capture_output=True,
    )


def build_remote_script(source, directory, ciphertext):
    encoded = base64.b64encode(ciphertext).decode()
    digest = hashlib.sha256(ciphertext).hexdigest()

    start = source.index("REMOTE_SCRIPT=\"$(cat <<SCRIPT")
    end = source.index("\nSCRIPT\n)\"", start)

    remote = source[start:end]

    remote = remote.split("\n", 1)[1]

    remote = remote.replace(
        'DIR="/var/lib/learningsteps-recovery"',
        f'DIR="{directory}"',
    )

    remote = remote.replace(
        "$CIPHER_B64", encoded
    ).replace(
        "$EXPECTED_SHA", digest
    )

    # Convert escaped outer-shell variables to remote variables.
    remote = remote.replace(r"\$", "$")

    return remote


def execute_remote(script):
    test_script = """
stat() {
    if [[ "$1" == "-c" && "$2" == "%u" ]]; then
        printf '0\\n'
    else
        command stat "$@"
    fi
}
""" + script

    return subprocess.run(
        ["bash", "-c", test_script],
        capture_output=True,
        text=True,
    )


def main():
    source = SOURCE.read_text()

    with tempfile.TemporaryDirectory() as temp:
        directory = pathlib.Path(temp)

        identity = directory / "recipient-identity.txt"

        run("age-keygen", "-o", str(identity))
        recipient = run("age-keygen", "-y", str(identity)).strip()

        identity.chmod(0o600)

        first = directory / "first.age"
        second = directory / "second.age"
        different = directory / "different.age"

        encrypt(recipient, b"test-password", first)
        encrypt(recipient, b"test-password", second)
        encrypt(recipient, b"other-password", different)

        print("[1/3] First transfer")

        remote = build_remote_script(
            source, directory, first.read_bytes()
        )
        result = execute_remote(remote)

        assert "__LS_TRANSPORT_RC__=0" in result.stdout, (
            result.stdout, result.stderr
        )

        target = directory / "postgres-admin-password.age"
        assert target.exists()

        original_hash = hashlib.sha256(
            target.read_bytes()
        ).hexdigest()

        print("PASS: Initial transfer")

        print("[2/3] Retry with identical password")

        remote = build_remote_script(
            source, directory, second.read_bytes()
        )
        result = execute_remote(remote)

        assert "__LS_TRANSPORT_RC__=0" in result.stdout, (
            result.stdout, result.stderr
        )

        assert hashlib.sha256(
            target.read_bytes()
        ).hexdigest() == original_hash

        print("PASS: Existing ciphertext retained")

        print("[3/3] Retry with different password")

        remote = build_remote_script(
            source, directory, different.read_bytes()
        )
        result = execute_remote(remote)

        assert "__LS_TRANSPORT_RC__=0" not in result.stdout
        assert hashlib.sha256(
            target.read_bytes()
        ).hexdigest() == original_hash

        print("PASS: Different password rejected")
        print("PASS: Existing ciphertext unchanged")

        print("[4/5] Rejecting symbolic links")

        target.unlink()
        target.symlink_to(first)

        result = execute_remote(
            build_remote_script(
                source, directory, second.read_bytes()
            )
        )

        assert "__LS_TRANSPORT_RC__=0" not in result.stdout
        assert target.is_symlink()

        print("PASS: Symlink rejected")

        print("[5/5] Rejecting unsafe permissions")

        target.unlink()
        target.write_bytes(first.read_bytes())
        target.chmod(0o644)

        result = execute_remote(
            build_remote_script(
                source, directory, second.read_bytes()
            )
        )

        assert "__LS_TRANSPORT_RC__=0" not in result.stdout
        assert target.read_bytes() == first.read_bytes()

        print("PASS: Unsafe permissions rejected")

    print("PASS: Remote transport integration tests completed")


if __name__ == "__main__":
    main()
