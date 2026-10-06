import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from jinja2 import Environment, StrictUndefined, select_autoescape

from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml
from utils.roles.mapping import ROLE_FILE_TEMPL_COMPOSE, ROLE_FILE_VARS_MAIN

ROLE_DIR = PROJECT_ROOT / "roles/web-app-penpot"

GETENT_STUB = """#!/usr/bin/env bash
name="${2:-}"
if [[ "${name}" != *. ]]; then
\techo "172.30.0.10 ${name}.infinito.test"
\texit 0
fi
lookups=$(( $(cat "${STUB_DIR}/absolute-lookups" 2>/dev/null || echo 0) + 1 ))
echo "${lookups}" >"${STUB_DIR}/absolute-lookups"
if [ "${lookups}" -le "${STUB_UNKNOWN_LOOKUPS}" ]; then
\texit 2
fi
echo "192.168.48.5 ${name%.}"
"""

NGINX_STUB = """#!/usr/bin/env bash
cat "${STUB_DIR}/absolute-lookups" 2>/dev/null || echo 0
"""

QUIET_STUB = """#!/usr/bin/env bash
exit 0
"""


def start_guard() -> str:
    template = read_text(str(ROLE_DIR / ROLE_FILE_TEMPL_COMPOSE))
    guard = re.search(r"^\s+- '(until getent hosts .+)'$", template, re.MULTILINE)
    names = load_yaml(str(ROLE_DIR / ROLE_FILE_VARS_MAIN))
    env = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    return env.from_string(guard.group(1)).render(
        PENPOT_BACKEND_SERVICE=names["PENPOT_BACKEND_SERVICE"],
        PENPOT_EXPORTER_SERVICE=names["PENPOT_EXPORTER_SERVICE"],
    )


class TestFrontendStartGuard(unittest.TestCase):
    def absolute_lookups_until_nginx_starts(self, failing_absolute_lookups: int) -> int:
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp)
            stubs = (
                ("getent", GETENT_STUB),
                ("nginx", NGINX_STUB),
                ("sleep", QUIET_STUB),
            )
            for name, body in stubs:
                stub = bin_dir / name
                stub.write_text(body)
                stub.chmod(0o755)
            env = {k: v for k, v in os.environ.items() if k != "BASH_ENV"}
            env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
            env["STUB_DIR"] = tmp
            env["STUB_UNKNOWN_LOOKUPS"] = str(failing_absolute_lookups)
            done = subprocess.run(
                ["bash", "-c", start_guard()],
                env=env,
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            self.assertEqual(done.returncode, 0, done.stderr)
            return int(done.stdout)

    def test_nginx_waits_until_the_services_resolve_without_the_search_domain(self):
        self.assertEqual(self.absolute_lookups_until_nginx_starts(3), 5)

    def test_nginx_starts_at_once_when_the_services_are_known(self):
        self.assertEqual(self.absolute_lookups_until_nginx_starts(0), 2)


if __name__ == "__main__":
    unittest.main()
