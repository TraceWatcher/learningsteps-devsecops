#!/usr/bin/env python3

import fcntl
import os
import pathlib
import re
import subprocess
import sys
import tempfile

KEY_DIR = pathlib.Path("/var/lib/learningsteps-recovery")
KEY_FILE = KEY_DIR / "recipient-identity.txt"
LOCK_FILE = KEY_DIR / ".recipient.lock"


def main():
    os.umask(0o077)

    KEY_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    KEY_DIR.chmod(0o700)

    with open(LOCK_FILE, "a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)

        if KEY_FILE.exists() or KEY_FILE.is_symlink():
            raise RuntimeError(
                "Recipient identity already exists"
            )

        with tempfile.TemporaryDirectory(
            prefix=".recipient-",
            dir=KEY_DIR,
        ) as temporary_directory:

            temporary_key = (
                pathlib.Path(temporary_directory)
                / "identity.txt"
            )

            subprocess.run(
                ["age-keygen", "-o", str(temporary_key)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
            )

            temporary_key.chmod(0o600)

            result = subprocess.run(
                ["age-keygen", "-y", str(temporary_key)],
                capture_output=True,
                text=True,
                check=True,
            )

            recipient = result.stdout.strip()

            if not re.fullmatch(
                r"age1[023456789acdefghjklmnpqrstuvwxyz]+",
                recipient,
            ):
                raise RuntimeError("Invalid AGE recipient")

            # Atomic publication under an exclusive lock.
            # Hard-link creation refuses to replace an existing file.
            os.link(temporary_key, KEY_FILE)
            KEY_FILE.chmod(0o600)

    print("PASS: Recipient identity generated")
    print("RECIPIENT=" + recipient)
    print("PASS: Private identity retained on VM")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(
            f"ERROR: {type(exc).__name__}: "
            "Recipient generation failed",
            file=sys.stderr,
        )
        sys.exit(1)
