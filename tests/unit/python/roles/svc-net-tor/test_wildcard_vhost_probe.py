from __future__ import annotations

import unittest
from typing import TYPE_CHECKING

from utils.cache.files import read_text

from . import PROJECT_ROOT
from ._probe import run_probe

if TYPE_CHECKING:
    import subprocess

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


def _run(script: str) -> subprocess.CompletedProcess[str]:
    """Args:
        script: the text of test.sh to run.

    Returns:
        The finished probe over a site vhost and a wildcard vhost of one onion.
        The curl stub answers the wildcard-derived host with a redirect to a
        name Tor cannot resolve, so following it ends in HTTP 000, and reports
        every request with whether it followed redirects on stderr.
    """
    return run_probe(script, (f"blog.{ONION}", WILDCARD), CURL_STUB, 1)


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
