from __future__ import annotations

import unittest

from utils.cache.files import read_text

from . import PROJECT_ROOT
from ._probe import run_probe

TEST_SH = PROJECT_ROOT / "roles" / "svc-net-tor" / "files" / "test" / "test.sh"
SITE = "blog.example.onion"
EXIT_CHECKED = '"${rc}" -eq 0 && '
COUNTED_CURL = """\
calls="$(dirname "$0")/calls"
n=$(( $(cat "${calls}" 2>/dev/null || echo 0) + 1 ))
echo "${n}" > "${calls}"
printf 'call %s: %s\\n' "${n}" "$*" >&2
"""
REDIRECT_THEN_TIMEOUT = COUNTED_CURL + "printf 302\nexit 28\n"
STALL_THEN_ANSWER = (
    COUNTED_CURL
    + """\
if [ "${n}" -eq 1 ]; then
	printf 000
	exit 28
fi
printf 200
"""
)


def _calls(stderr: str) -> list[str]:
    return [line for line in stderr.splitlines() if line.startswith("call ")]


class TestTheProbeRetries(unittest.TestCase):
    def test_a_status_with_a_failed_curl_is_no_answer(self) -> None:
        result = run_probe(read_text(str(TEST_SH)), (SITE,), REDIRECT_THEN_TIMEOUT, 2)

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(f"[FAIL] {SITE}", result.stdout)
        self.assertEqual(len(_calls(result.stderr)), 2)

    def test_negative_control_a_probe_ignoring_curl_passes_the_timeout(self) -> None:
        script = read_text(str(TEST_SH))
        self.assertIn(EXIT_CHECKED, script)

        result = run_probe(
            script.replace(EXIT_CHECKED, "", 1), (SITE,), REDIRECT_THEN_TIMEOUT, 2
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_only_a_retry_asks_tor_for_a_fresh_circuit(self) -> None:
        result = run_probe(read_text(str(TEST_SH)), (SITE,), STALL_THEN_ANSWER, 3)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        first, second = _calls(result.stderr)
        self.assertNotIn("--proxy-user", first)
        self.assertIn("--proxy-user probe-2:x", second)


if __name__ == "__main__":
    unittest.main()
