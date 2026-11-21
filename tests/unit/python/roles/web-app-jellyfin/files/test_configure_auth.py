import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import NamedTuple

from utils import PROJECT_ROOT
from utils.cache.files import read_text

SCRIPT = PROJECT_ROOT / "roles/web-app-jellyfin/files/shell/configure-auth.sh"

AUTH_RESPONSE = (
    '{"User":{"Name":"administrator","ServerId":"e5c","Id":"a1b2c3d4",'
    '"HasPassword":true,"Configuration":{"PlayDefaultAudioTrack":true},'
    '"Policy":{"IsAdministrator":true}},"SessionInfo":{"Id":"s1"},'
    '"AccessToken":"tok-abc-123","ServerId":"e5c"}'
)

_SED = re.compile(r"sed -n '(s/\.\*\"(?:AccessToken|User)\".*?/p)'")

API = "http://jellyfin.test"
TOKEN = "tok-abc-123"
PIN = "pin-7788"
PIN_TOKEN = "pin-tok-456"
PIN_AUTH_RESPONSE = AUTH_RESPONSE.replace(TOKEN, PIN_TOKEN)
TOKEN_HEADER = f'Authorization: MediaBrowser Token="{TOKEN}"'
PIN_TOKEN_HEADER = f'Authorization: MediaBrowser Token="{PIN_TOKEN}"'
CONFIGURE_CALLS = [
    (
        f"{API}/Plugins/505ce9d1-d916-42fa-86ca-673ef241d7df/Configuration",
        TOKEN_HEADER,
    ),
    (f"{API}/System/Configuration/branding", TOKEN_HEADER),
]


class _Scenario(NamedTuple):
    phase: str
    password_accepted: bool
    writes: list[str]
    calls: list[tuple[str, str]]


SCENARIOS = {
    "install": _Scenario(
        "install",
        True,
        [TOKEN_HEADER],
        [
            (f"{API}/Repositories", TOKEN_HEADER),
            (f"{API}/Packages/Installed/SSO%20Authentication", TOKEN_HEADER),
        ],
    ),
    "configure": _Scenario("configure", True, [TOKEN_HEADER], CONFIGURE_CALLS),
    "password-reset": _Scenario(
        "configure",
        False,
        [PIN_TOKEN_HEADER, TOKEN_HEADER],
        [(f"{API}/Users/a1b2c3d4/Password", PIN_TOKEN_HEADER), *CONFIGURE_CALLS],
    ),
}

_RECORD = r"""#!/usr/bin/env bash
record() {
  local file="$1" IFS=$'\x1f'
  shift
  printf '%s\x1e' "$*" >> "${STUB_LOG}/${file}"
}
"""

STUBS = {
    "container": _RECORD
    + r"""record argv container "$@"
[ "$1" = "exec" ] || exit 0
shift
stdin=/dev/null
if [ "$1" = "-i" ]; then
  shift
  stdin="$(mktemp "${STUB_LOG}/stdin.XXXXXX")"
  cat > "${stdin}"
  record stdin "${@:2}" "$(cat "${stdin}")"
fi
shift
export TMPDIR="${STUB_CONTAINER_TMP}"
exec "${@//\/config\//${STUB_CONFIG}/}" < "${stdin}"
""",
    "curl": _RECORD
    + r"""record argv curl "$@"
url=""
body=""
prev=""
files=()
for arg in "$@"; do
  case "${arg}" in
    http://*) url="${arg}" ;;
    @-) body="$(cat)" ;;
  esac
  if [ "${prev}" = "-H" ] && [ "${arg:0:1}" = "@" ]; then
    files+=("${arg:1}")
  fi
  prev="${arg}"
done
for file in "${files[@]}"; do
  record headers "${url}" "${file}" "$(cat "${file}")"
done
case "${url}" in
  */Users/AuthenticateByName)
    case "${body}" in
      *"\"Pw\":\"${STUB_PIN}\""*) printf '%s' "${STUB_PIN_AUTH_RESPONSE}" ;;
      *) [ ! -e "${STUB_LOG}/password-accepted" ] || printf '%s' "${STUB_AUTH_RESPONSE}" ;;
    esac
    ;;
  */Users/ForgotPassword)
    printf '{"Pin":"%s"}' "${STUB_PIN}" > "${STUB_CONFIG}/passwordreset.json"
    ;;
  */Users/*/Password) : > "${STUB_LOG}/password-accepted" ;;
esac
""",
    "sleep": "#!/bin/sh\nexit 0\n",
}


class _Run(NamedTuple):
    returncode: int
    output: str
    container_tmp: Path
    argvs: list[list[str]]
    stdins: list[list[str]]
    headers: list[list[str]]

    @property
    def header_files(self) -> set[str]:
        return {path for _, path, _ in self.headers}


def _records(path: Path) -> list[list[str]]:
    if not path.exists():
        return []
    return [
        record.split("\x1f") for record in read_text(str(path)).split("\x1e") if record
    ]


def _run(root: Path, scenario: _Scenario) -> _Run:
    stubs, log, tmp, container_tmp, config = (
        root / name for name in ("bin", "log", "tmp", "container-tmp", "config")
    )
    for directory in (stubs, log, tmp, container_tmp, config):
        directory.mkdir(parents=True)
    for name, body in STUBS.items():
        stub = stubs / name
        stub.write_text(body)
        stub.chmod(0o755)
    if scenario.password_accepted:
        (log / "password-accepted").touch()
    done = subprocess.run(
        ["bash", str(SCRIPT)],
        input="admin-secret\nbind-secret\noidc-secret\n",
        capture_output=True,
        text=True,
        env={
            "PATH": f"{stubs}{os.pathsep}{os.environ['PATH']}",
            "TMPDIR": str(tmp),
            "STUB_LOG": str(log),
            "STUB_CONFIG": str(config),
            "STUB_CONTAINER_TMP": str(container_tmp),
            "STUB_PIN": PIN,
            "STUB_AUTH_RESPONSE": AUTH_RESPONSE,
            "STUB_PIN_AUTH_RESPONSE": PIN_AUTH_RESPONSE,
            "JELLYFIN_API": API,
            "JELLYFIN_CT": "jellyfin",
            "JELLYFIN_PHASE": scenario.phase,
            "JELLYFIN_ADMIN_USERNAME": "administrator",
            "JELLYFIN_SSO_ENABLED": "true",
            "JELLYFIN_LDAP_ENABLED": "false",
            "JELLYFIN_LOGIN_SSO_ENABLED": "true",
            "JELLYFIN_LOGIN_FORM_ENABLED": "true",
            "JELLYFIN_SSO_PLUGIN_MANIFEST": "http://plugins.test/manifest.json",
            "JELLYFIN_OIDC_ISSUER": "http://auth.test/realms/main",
            "JELLYFIN_OIDC_CLIENT_ID": "jellyfin",
            "JELLYFIN_OIDC_ADMIN_ROLE": "jellyfin-administrator",
            "JELLYFIN_OIDC_ROLE_CLAIM": "roles",
            "JELLYFIN_OIDC_USERNAME_CLAIM": "preferred_username",
            "JELLYFIN_OIDC_DISABLE_HTTPS": "true",
        },
        timeout=60,
        check=False,
    )
    return _Run(
        done.returncode,
        done.stdout + done.stderr,
        container_tmp,
        _records(log / "argv"),
        _records(log / "stdin"),
        _records(log / "headers"),
    )


def _apply(expression: str, payload: str) -> str:
    done = subprocess.run(
        ["sed", "-n", expression],
        input=payload,
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


class TestConfigureAuthExtraction(unittest.TestCase):
    """One AuthenticateByName response must yield both the token and the user id.

    Authenticating twice with the fixed DeviceId in CLIENT_HDR makes Jellyfin
    revoke the first session, so the token from an earlier call is already dead
    when the password change presents it.
    """

    def setUp(self) -> None:
        self.source = read_text(str(SCRIPT))
        self.expressions = _SED.findall(self.source)

    def test_the_script_keeps_exactly_one_authenticate_call_site_per_field(self):
        self.assertEqual(self.source.count("Users/AuthenticateByName"), 1)

    def test_one_response_yields_both_the_token_and_the_user_id(self):
        self.assertEqual(len(self.expressions), 2)
        extracted = {
            _apply(expression, AUTH_RESPONSE) for expression in self.expressions
        }
        self.assertEqual(extracted, {"tok-abc-123", "a1b2c3d4"})

    def test_a_response_without_a_token_extracts_nothing(self):
        for expression in self.expressions:
            with self.subTest(expression=expression):
                self.assertEqual(_apply(expression, '{"Error":"Unauthorized"}'), "")


class TestConfigureAuthKeepsTheTokenOffArgv(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(tmp.cleanup)
        cls.runs = {
            name: _run(Path(tmp.name) / name, scenario)
            for name, scenario in SCENARIOS.items()
        }

    def test_every_scenario_finishes_against_the_stubbed_server(self) -> None:
        for name, run in self.runs.items():
            with self.subTest(scenario=name):
                self.assertEqual(run.returncode, 0, run.output)

    def test_no_container_or_curl_argv_carries_a_session_token(self) -> None:
        for name, run in self.runs.items():
            with self.subTest(scenario=name):
                self.assertEqual({argv[0] for argv in run.argvs}, {"container", "curl"})
                leaks = [
                    argv
                    for argv in run.argvs
                    if any(token in arg for arg in argv for token in (TOKEN, PIN_TOKEN))
                ]
                self.assertEqual(leaks, [])

    def test_every_authenticated_call_reads_its_header_from_a_file(self) -> None:
        for name, run in self.runs.items():
            with self.subTest(scenario=name):
                calls = [(url, header) for url, _, header in run.headers]
                self.assertEqual(sorted(calls), sorted(SCENARIOS[name].calls))

    def test_the_header_file_lives_inside_the_container(self) -> None:
        for name, run in self.runs.items():
            with self.subTest(scenario=name):
                self.assertEqual(
                    {Path(path).parent for path in run.header_files},
                    {run.container_tmp},
                )

    def test_the_token_reaches_the_header_file_on_stdin(self) -> None:
        for name, run in self.runs.items():
            with self.subTest(scenario=name):
                writes = [
                    record
                    for record in run.stdins
                    if "MediaBrowser Token" in record[-1]
                ]
                self.assertEqual(
                    [record[-1] for record in writes], SCENARIOS[name].writes
                )
                for *command, _ in writes:
                    self.assertTrue(
                        any(
                            path in arg for arg in command for path in run.header_files
                        ),
                        command,
                    )

    def test_the_header_file_is_removed_inside_the_container_on_exit(self) -> None:
        for name, run in self.runs.items():
            with self.subTest(scenario=name):
                self.assertTrue(run.header_files)
                for path in run.header_files:
                    self.assertFalse(Path(path).exists(), path)
                    touches = [
                        argv for argv in run.argvs if any(path in a for a in argv)
                    ]
                    self.assertEqual(touches[-1][:2], ["container", "exec"])


if __name__ == "__main__":
    unittest.main()
