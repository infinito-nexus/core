from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import read_text
from utils.networks.reachability import TOR, network

from . import PROJECT_ROOT

TEST_SH = PROJECT_ROOT / "roles" / "svc-net-tor" / "files" / "test" / "test.sh"
ONION = "example.onion"
WILDCARD = f"*.user.blog.{ONION}"
PROBED = f"http://probe.user.blog.{ONION}/"
SITE = f"http://blog.{ONION}/"
NO_FOLLOW = "\t\tfollow=()\n"
CURL_STUB = """\
url="${@: -1}"
follow=no
case " $* " in
*" --location "*) follow=yes ;;
esac
printf '%s follow=%s\\n' "${url}" "${follow}" >&2
case "${url}" in
*'*'*)
	printf 000
	exit 6
	;;
*://probe.*)
	if [ "${follow}" = yes ]; then
		printf 000
		exit 6
	fi
	printf 302
	;;
*) printf 200 ;;
esac
"""


def _stub(path: Path, body: str) -> None:
    path.write_text(f"#!/usr/bin/env bash\n{body}\n", encoding="utf-8")
    path.chmod(0o755)


def _run(script: str) -> subprocess.CompletedProcess[str]:
    """Args:
        script: the text of test.sh to run.

    Returns:
        The finished probe over a site vhost and a wildcard vhost of one onion.
        The curl stub answers the wildcard-derived host with a redirect to a
        name Tor cannot resolve, so following it ends in HTTP 000, and reports
        every request with whether it followed redirects on stderr.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "http").mkdir()
        for vhost in (f"blog.{ONION}", WILDCARD):
            (root / "http" / f"{vhost}.conf").write_text("", encoding="utf-8")
        (root / "test.sh").write_text(script, encoding="utf-8")
        _stub(root / "onion_ports.py", "exit 0")
        bin_dir = root / "bin"
        bin_dir.mkdir()
        _stub(bin_dir / "curl", CURL_STUB)
        return subprocess.run(
            ["bash", str(root / "test.sh")],
            env={
                "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
                "TOR_SOCKS": "127.0.0.1:9050",
                "ONION_SUFFIX": network(TOR).suffix,
                "NGINX_SERVERS_DIR": str(root),
                "RETRIES": "1",
                "SLEEP_SECONDS": "0",
                "TOR_DNSMASQ_CONF": str(root / "tor-onion.conf"),
                "TOR_CONTAINER": "tor",
                "TOR_FLAVOR": "public",
            },
            capture_output=True,
            text=True,
            check=False,
        )


class TestTheWildcardVhostAnswersForItself(unittest.TestCase):
    def test_the_wildcard_vhost_counts_by_its_own_answer(self) -> None:
        result = _run(read_text(str(TEST_SH)))

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f"{PROBED} follow=no", result.stderr.splitlines())
        self.assertIn(f"{SITE} follow=yes", result.stderr.splitlines())
        self.assertIn("[INFO] 2 probed, 0 failed", result.stdout)

    def test_negative_control_following_the_wildcard_redirect_fails(self) -> None:
        script = read_text(str(TEST_SH))
        self.assertIn(NO_FOLLOW, script)

        result = _run(script.replace(NO_FOLLOW, "", 1))

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(f"{PROBED} follow=yes", result.stderr.splitlines())
        self.assertIn(f"[FAIL] {WILDCARD}", result.stdout)


if __name__ == "__main__":
    unittest.main()
