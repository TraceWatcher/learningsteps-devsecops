#!/usr/bin/env python3
"""Build an offline Azure Run Command installation payload."""

import argparse
import base64
import hashlib
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent

FILES = (
    "restore-keyvault-secret.py",
    "remote-restore-keyvault.py",
)

HEADER = """#!/usr/bin/env bash
set -euo pipefail
umask 077

[[ "$(id -u)" == "0" ]] || {
  echo "ERROR: Root required" >&2
  exit 1
}

DIR="/opt/learningsteps-recovery"

[[ -d /opt && ! -L /opt ]] || exit 1
[[ "$(stat -c %u /opt)" == "0" ]] || exit 1

# Reject group- or world-writable installation parent.
[[ -z "$(find /opt -maxdepth 0 -perm /022 -print)" ]] || exit 1

if [[ -e "$DIR" || -L "$DIR" ]]; then
  [[ -d "$DIR" && ! -L "$DIR" ]] || exit 1
else
  mkdir -m 700 -- "$DIR"
fi

[[ "$(stat -c %u "$DIR")" == "0" ]] || exit 1
[[ "$(stat -c %a "$DIR")" == "700" ]] || exit 1

# Lock the protected installation directory itself.
# No separate lock file needs to be created.
exec 9<"$DIR"
flock -x 9

TMP="$(mktemp -d "$DIR/.stage.XXXXXXXX")"
trap 'rm -rf -- "$TMP"' EXIT
"""


def build_payload():
    chunks = [HEADER]

    for index, name in enumerate(FILES, 1):
        source = ROOT / name

        if source.is_symlink() or not source.is_file():
            raise RuntimeError(f"Unsafe source file: {name}")

        data = source.read_bytes()

        if not data or len(data) > 100_000:
            raise RuntimeError(f"Invalid source size: {name}")

        digest = hashlib.sha256(data).hexdigest()
        encoded = base64.b64encode(data).decode("ascii")
        marker = f"__LS_FILE_{index}__"

        chunks.append(
            f'\nbase64 -d > "$TMP/{name}" <<\'{marker}\'\n'
            f"{encoded}\n"
            f"{marker}\n"
            f'chmod 600 "$TMP/{name}"\n'
            f'echo "{digest}  $TMP/{name}" | sha256sum -c --status\n'
        )

    for name in FILES:
        chunks.append(
            f"""
TARGET="$DIR/{name}"

if [[ -e "$TARGET" || -L "$TARGET" ]]; then
  [[ -f "$TARGET" && ! -L "$TARGET" ]] || exit 1
  [[ "$(stat -c %u "$TARGET")" == "0" ]] || exit 1
  [[ "$(stat -c %a "$TARGET")" == "600" ]] || exit 1

  cmp -s "$TMP/{name}" "$TARGET" || {{
    echo "ERROR: Existing module differs: {name}" >&2
    exit 1
  }}
else
  ln "$TMP/{name}" "$TARGET"
fi

cmp -s "$TMP/{name}" "$TARGET" || exit 1
echo "PASS: Module verified: {name}"
"""
        )

    chunks.append(
        '\necho "PASS: Recovery modules installed and verified"\n'
    )

    return "".join(chunks)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    output = Path(args.output)

    # Never overwrite an existing payload or follow a symlink.
    fd = os.open(
        output,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            payload = build_payload()

            wrapped = (
                "set +e\n"
                "(\n"
                + payload
                + "\n)\n"
                "rc=$?\n"
                "printf '__LS_INSTALL_RC__=%s\\n' \"$rc\"\n"
                "exit 0\n"
            )

            stream.write(wrapped)
    except BaseException:
        output.unlink(missing_ok=True)
        raise

    print("PASS: Installation payload generated")
    print(f"Output: {output}")
    print("INFO: No Azure operation executed")


if __name__ == "__main__":
    main()
