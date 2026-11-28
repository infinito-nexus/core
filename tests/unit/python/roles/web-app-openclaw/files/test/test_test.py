from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

from utils.cache.files import PROJECT_ROOT, read_text

ROLE = PROJECT_ROOT / "roles" / "web-app-openclaw"
SCRIPT = ROLE / "files" / "test" / "test.sh"
TEST_ENV = ROLE / "templates" / "test.env.j2"
PUBLISHED_KEY = "GATEWAY_PUBLISHED"
CURL = """url="${@: -1}"
case "${url}" in
  */healthz) code="${HEALTHZ_CODE}" ;;
  *) code="${INVOKE_CODE}" ;;
esac
printf '%s' "${code}"
[ "${code}" != "000" ] || exit 7"""


def _executable(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/usr/bin/env bash\n{body}\n")
    path.chmod(0o755)


def published(compose_mode: str) -> str:
    """Args:
        compose_mode: the effective deploy mode of the role.

    Returns:
        The value ``templates/test.env.j2`` renders for ``GATEWAY_PUBLISHED``.
    """
    prefix = f"{PUBLISHED_KEY}="
    line = next(
        line
        for line in read_text(str(TEST_ENV)).splitlines()
        if line.startswith(prefix)
    )
    templar = Templar(loader=DataLoader(), variables={"compose_mode": compose_mode})
    return str(templar.template(trust_as_template(line[len(prefix) :])))


class TestGatewayPortProbe(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.bin = self.root / "bin"
        _executable(self.bin / "container", "echo paired")
        _executable(self.bin / "curl", CURL)
        shutil.copy(SCRIPT, self.root / "test.sh")
        self.env = {
            **os.environ,
            "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
            "FORGED_USER": "administrator",
            "GATEWAY_HOST": "127.0.0.1",
            "GATEWAY_PORT": "8090",
            "MCP_CLIENT_CONTAINER": "openclaw",
            "MCP_TEST_ENABLED": "false",
            "PROXY_SECRET_HEADER_PREFIX": "x-infinito-sso-proxy",
            "TRUSTED_PROXY_ENABLED": "true",
        }

    def _run(self, mode: str, healthz: str, invoke: str = "401"):
        self.env.update(
            {
                PUBLISHED_KEY: published(mode),
                "HEALTHZ_CODE": healthz,
                "INVOKE_CODE": invoke,
            }
        )
        return subprocess.run(
            ["bash", str(self.root / "test.sh")],
            env=self.env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

    def test_the_template_publishes_the_port_only_in_compose(self) -> None:
        self.assertEqual("true", published("compose"))
        self.assertEqual("false", published("swarm"))

    def test_swarm_passes_when_the_unpublished_port_does_not_answer(self) -> None:
        run = self._run("swarm", healthz="000")
        self.assertEqual(0, run.returncode, run.stdout + run.stderr)
        self.assertIn("the gateway port is not published", run.stdout)
        self.assertNotIn("a forged identity", run.stdout)

    def test_swarm_fails_when_the_gateway_port_answers(self) -> None:
        run = self._run("swarm", healthz="200")
        self.assertNotEqual(0, run.returncode, run.stdout)
        self.assertIn("swarm must not publish the gateway port", run.stderr)

    def test_compose_refuses_both_forged_identities(self) -> None:
        run = self._run("compose", healthz="200")
        self.assertEqual(0, run.returncode, run.stdout + run.stderr)
        self.assertEqual(2, run.stdout.count("a forged identity"), run.stdout)

    def test_compose_fails_when_the_published_port_does_not_answer(self) -> None:
        run = self._run("compose", healthz="000")
        self.assertNotEqual(0, run.returncode, run.stdout)
        self.assertIn("the published gateway port must answer /healthz", run.stderr)

    def test_compose_fails_when_a_forged_identity_gets_through(self) -> None:
        run = self._run("compose", healthz="200", invoke="200")
        self.assertNotEqual(0, run.returncode, run.stdout)
        self.assertIn("must be refused with HTTP 401, got 200", run.stderr)


if __name__ == "__main__":
    unittest.main()
