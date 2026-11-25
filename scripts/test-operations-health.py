#!/usr/bin/env python3
"""Offline tests for the public HTTPS checks used after Operations start."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("check-operations-health.sh")
APP_URL = "https://learningsteps.6b042d6926882100015ba12e.westeurope.aksapp.io"
OLD_URL = "https://learningsteps.6aff4a07cf83170001eabf87.westeurope.aksapp.io"
READY_PATH = "/api/health/ready"
READY_BODY = '{"status":"ready","database":"connected"}'
PRIVATE_MARKER = "private-response-marker"

CURL = r"""
import json
import os
import sys
from pathlib import Path

queue = Path(os.environ["CURL_QUEUE"])
calls = Path(os.environ["CURL_CALLS"])
args = sys.argv[1:]
with calls.open("a") as log:
    print(json.dumps(args), file=log)
pending = json.loads(queue.read_text())
if not pending:
    sys.exit(99)
response = pending.pop(0)
queue.write_text(json.dumps(pending))
if response["exit_code"]:
    print("private-response-marker", file=sys.stderr)
    sys.exit(response["exit_code"])
destination = Path(args[args.index("--output") + 1])
destination.write_text(response["body"])
print(f'{response["status"]}\n{response["content_type"]}', end="")
"""


def response(status=200, content_type="application/json", body=READY_BODY, *, exit_code=0):
    return {"status": status, "content_type": content_type, "body": body, "exit_code": exit_code}


class OperationsHealthTest(unittest.TestCase):
    def run_check(self, responses, *, base_url=APP_URL, args=()):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            curl = root / "curl"
            curl.write_text(f"#!{sys.executable}\n{CURL}")
            curl.chmod(0o700)
            sleep = root / "sleep"
            sleep.write_text("#!/bin/sh\nexit 0\n")
            sleep.chmod(0o700)
            queue = root / "queue"
            queue.write_text(json.dumps(responses))
            calls = root / "calls"
            calls.touch()
            result = subprocess.run(
                ["bash", str(SCRIPT), *args],
                env={
                    "PATH": os.pathsep.join((directory, os.defpath)),
                    "APP_URL": base_url,
                    "CURL_QUEUE": str(queue),
                    "CURL_CALLS": str(calls),
                },
                capture_output=True,
                text=True,
                timeout=15,
            )
            self.assertEqual(json.loads(queue.read_text()), [])
            self.assertNotIn(PRIVATE_MARKER, result.stdout + result.stderr)
            commands = [json.loads(line) for line in calls.read_text().splitlines()]
            for argv in commands:
                self.assertEqual(argv[0], "--disable")
                self.assertEqual(argv[argv.index("--proto") + 1], "=https")
                self.assertEqual(
                    argv[argv.index("--write-out") + 1], r"%{http_code}\n%{content_type}"
                )
                self.assertTrue(set(argv).isdisjoint({"-k", "--insecure", "-L", "--location"}))
            return result, [argv[-1] for argv in commands]

    def assert_ready_failure(self, error, reply, *, base_url=APP_URL):
        result, urls = self.run_check([reply] * 30, base_url=base_url)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(urls, [base_url + READY_PATH] * 30)
        self.assertEqual(result.stderr.count(error), 30, result.stderr)
        self.assertNotIn("PASS:", result.stdout)

    def test_current_config_uses_public_api_path_and_retains_other_http_checks(self):
        result, urls = self.run_check(
            [
                response(content_type="Application/JSON; charset=utf-8"),
                response(content_type="text/html", body="<html>Frontend</html>"),
                response(status=401, body='{"detail":"Authentication required"}'),
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(urls, [APP_URL + READY_PATH, APP_URL + "/", APP_URL + "/api/entries"])
        self.assertIn("PASS: API-Readiness und Datenbankverbindung bestätigt", result.stdout)

    def test_stale_configured_hostname_does_not_follow_redirects_to_another_origin(self):
        self.assert_ready_failure(
            "Erhalten 301, erwartet 200",
            response(status=301, content_type="text/plain"),
            base_url=OLD_URL,
        )

    def test_nxdomain_for_previous_hostname_is_reported_without_raw_diagnostics(self):
        self.assert_ready_failure("DNS-Fehler", response(exit_code=6), base_url=OLD_URL)

    def test_tls_errors_are_identified_separately(self):
        self.assert_ready_failure("TLS-Fehler", response(exit_code=60))

    def test_old_internal_path_and_non_https_or_credential_urls_are_rejected(self):
        for url in (
            APP_URL + "/health/ready",
            APP_URL + READY_PATH,
            APP_URL + ":443",
            APP_URL + "?token=" + PRIVATE_MARKER,
            APP_URL.replace("https://", f"https://{PRIVATE_MARKER}@"),
            APP_URL.replace("https://", "http://"),
            "",
        ):
            with self.subTest(url=url):
                result, urls = self.run_check([], base_url=url)
                self.assertEqual(result.returncode, 1)
                self.assertIn("OPERATIONS_APP_URL", result.stderr)
                self.assertEqual(urls, [])

    def test_validate_url_before_start_performs_no_requests(self):
        result, urls = self.run_check([], args=("--validate-url",))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(urls, [])

    def test_html_200_never_counts_as_ready(self):
        self.assert_ready_failure(
            "Unerwarteter Content-Type",
            response(
                content_type="text/html; charset=utf-8", body=f"<html>{PRIVATE_MARKER}</html>"
            ),
        )

    def test_json_header_alone_is_insufficient(self):
        for body in (
            f"<html>{PRIVATE_MARKER}</html>",
            '{"status":"ready","database":"disconnected"}',
            '{"status":"starting","database":"connected"}',
            READY_BODY + "\n" + READY_BODY,
        ):
            with self.subTest(body=body):
                self.assert_ready_failure("Unerwartete JSON-Antwort", response(body=body))

    def test_api_503_fails_even_if_payload_claims_readiness(self):
        self.assert_ready_failure("Erhalten 503, erwartet 200", response(status=503))

    def test_api_503_is_retried_before_success(self):
        result, urls = self.run_check(
            [response(status=503), response(), response(), response(status=401)]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Erhalten 503, erwartet 200", result.stderr)
        self.assertEqual(
            urls, [APP_URL + READY_PATH] * 2 + [APP_URL + "/", APP_URL + "/api/entries"]
        )


if __name__ == "__main__":
    unittest.main()
