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
SHOP = f"shop.{ONION}"
ERP = f"odoo.erp.{ONION}"
CLEARNET = "odoo.erp.example.com"
ONION_NO_FOLLOW = "\t\t\tfollow=()\n"
ROUTED_CURL = """\
url="${@: -1}"
fmt=""
prev=""
follow=no
for arg in "$@"; do
	if [ "${prev}" = -w ]; then fmt="${arg}"; fi
	if [ "${arg}" = --location ]; then follow=yes; fi
	prev="${arg}"
done
code=000
target=""
rc=0
while true; do
	printf '%s follow=%s\\n' "${url}" "${follow}" >&2
	case "${url}" in
ROUTES
	*)
		target=""
		rc=28
		break
		;;
	esac
	code="${answer%% *}"
	target="${answer#* }"
	if [ "${follow}" = no ] || [ "${code#3}" = "${code}" ]; then break; fi
	hops=$((${hops:-0} + 1))
	if [ "${hops}" -gt 50 ]; then
		rc=47
		break
	fi
	url="${target}"
done
out="${fmt//'%{http_code}'/${code}}"
printf '%s' "${out//'%{redirect_url}'/${target}}"
exit "${rc}"
"""


def _routed(
    script: str, vhost: str, routes: dict[str, str], retries: int
) -> subprocess.CompletedProcess[str]:
    """Args:
        script: the text of test.sh to run.
        vhost: the one onion vhost the probe discovers.
        routes: URL -> "<status> <redirect url>" answers of the curl stub;
            every other URL times out like a clearnet host behind Tor.
        retries: RETRIES of the run.

    Returns:
        The finished probe. The curl stub honours --location and the -w
        format, and reports every request it serves on stderr.
    """
    cases = "\n".join(
        f"\t'{url}') answer='{answer}' ;;" for url, answer in routes.items()
    )
    return run_probe(script, (vhost,), ROUTED_CURL.replace("ROUTES", cases), retries)


def _requests(result: subprocess.CompletedProcess[str]) -> list[str]:
    return [line for line in result.stderr.splitlines() if " follow=" in line]


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
        self.assertIn(f"{SITE} follow=no", result.stderr.splitlines())
        self.assertIn("[INFO] 2 probed, 0 failed", result.stdout)

    def test_negative_control_following_the_wildcard_redirect_fails(self) -> None:
        script = read_text(str(TEST_SH))
        self.assertIn(NO_FOLLOW, script)

        result = _run(script.replace(NO_FOLLOW, "", 1))

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(f"{PROBED} follow=yes", result.stderr.splitlines())
        self.assertIn(f"[FAIL] {WILDCARD}", result.stdout)


class TestTheOnionProbeFollowsOnlyInsideTheOnionNetwork(unittest.TestCase):
    def test_a_redirect_on_the_onion_host_is_followed(self) -> None:
        routes = {
            f"http://{SHOP}/": f"302 http://{SHOP}/login",
            f"http://{SHOP}/login": "200 ",
        }

        result = _routed(read_text(str(TEST_SH)), SHOP, routes, retries=1)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f"http://{SHOP}/login follow=no", _requests(result))
        self.assertIn("HTTP 200\n", result.stdout)

    def test_a_handover_out_of_the_onion_network_is_the_answer(self) -> None:
        routes = {f"http://{ERP}/": f"302 https://{CLEARNET}/"}

        result = _routed(read_text(str(TEST_SH)), ERP, routes, retries=1)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f"HTTP 302 -> handover {CLEARNET}\n", result.stdout)
        self.assertEqual(_requests(result), [f"http://{ERP}/ follow=no"])

    def test_a_redirect_on_the_onion_host_to_a_bad_gateway_fails(self) -> None:
        routes = {
            f"http://{SHOP}/": f"302 http://{SHOP}/broken",
            f"http://{SHOP}/broken": "502 ",
        }

        result = _routed(read_text(str(TEST_SH)), SHOP, routes, retries=1)

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(f"[FAIL] {SHOP}", result.stdout)
        self.assertIn("HTTP 502 ", result.stdout)

    def test_an_endless_redirect_on_the_onion_host_fails(self) -> None:
        routes = {f"http://{SHOP}/": f"302 http://{SHOP}/"}

        result = _routed(read_text(str(TEST_SH)), SHOP, routes, retries=1)

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(f"[FAIL] {SHOP}", result.stdout)

    def test_a_timeout_fails_after_every_retry(self) -> None:
        result = _routed(read_text(str(TEST_SH)), SHOP, {}, retries=2)

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("HTTP 000 ", result.stdout)
        self.assertEqual(len(_requests(result)), 2)

    def test_negative_control_following_the_handover_times_out(self) -> None:
        script = read_text(str(TEST_SH))
        self.assertIn(ONION_NO_FOLLOW, script)
        routes = {f"http://{ERP}/": f"302 https://{CLEARNET}/"}

        result = _routed(script.replace(ONION_NO_FOLLOW, "", 1), ERP, routes, retries=1)

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(f"https://{CLEARNET}/ follow=yes", _requests(result))
        self.assertIn(f"[FAIL] {ERP}", result.stdout)


if __name__ == "__main__":
    unittest.main()
