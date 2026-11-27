from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_any
from utils.docker.mirror import mirror_image
from utils.roles.mapping import ROLE_FILE_META_SERVICES

CACHE = PROJECT_ROOT / "scripts" / "tests" / "workspace" / "utils" / "cache.sh"
PROBE_SERVICES = PROJECT_ROOT / "roles" / "svc-db-openldap" / ROLE_FILE_META_SERVICES
PROBE_SERVICE = "openldap"
SEPARATOR = "\x1f"
GITHUB = {
    "GITHUB_REPOSITORY": "Acme/Core",
    "GITHUB_REPOSITORY_OWNER": "Acme",
    "INFINITO_GHCR_MIRROR_PREFIX": "mirror",
}
STRIPPED = ("OWNER", "REPO_PREFIX", "INFINITO_IMAGE_REPOSITORY", "COMPOSE_NETWORK")

FAKE_DOCKER = """#!/usr/bin/env bash
printf '%s\\x1f' "$@" >>"${FAKE_DOCKER_CALLS}"
printf '\\n' >>"${FAKE_DOCKER_CALLS}"
if [[ "$1" == build ]]; then
\tcp "${!#}/Dockerfile" "${FAKE_DOCKER_DOCKERFILE}"
\tprintf 'GET /debian/dists/trixie/InRelease\\n' >>"${FAKE_FRONTEND_LOG}"
fi
"""

DRIVER = """set -euo pipefail
source "${CACHE_SH}"
infra_cache() { printf 'package-cache-frontend\\n'; }
infra_docker() { cat "${FAKE_FRONTEND_LOG}"; }
probe_did_inner_build
"""


def run_probe(tmp: Path) -> tuple[subprocess.CompletedProcess, list[list[str]], str]:
    """Args:
        tmp: scratch directory holding the fake docker and its records.

    Returns:
        The probe's process, every docker call as its argv, and the
        Dockerfile the probe handed to ``docker build``.
    """
    bin_dir = tmp / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(FAKE_DOCKER, encoding="utf-8")
    docker.chmod(0o755)
    calls = tmp / "calls"
    dockerfile = tmp / "Dockerfile"
    frontend_log = tmp / "frontend.log"
    calls.touch()
    frontend_log.touch()
    env = {k: v for k, v in os.environ.items() if k not in STRIPPED}
    env.update(GITHUB)
    env.update(
        {
            "BASH_ENV": "",
            "PATH": f"{bin_dir}{os.pathsep}{env['PATH']}",
            "CACHE_SH": str(CACHE),
            "REPO_ROOT": str(PROJECT_ROOT),
            "PYTHON": sys.executable,
            "COMPOSE_NETWORK": "infinito-infra",
            "INFINITO_CACHE_PACKAGE_FRONTEND_IP": "10.47.0.2",
            "FAKE_DOCKER_CALLS": str(calls),
            "FAKE_DOCKER_DOCKERFILE": str(dockerfile),
            "FAKE_FRONTEND_LOG": str(frontend_log),
        }
    )
    proc = subprocess.run(
        ["bash", "-c", DRIVER],
        cwd=tmp,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    argvs = [
        line.split(SEPARATOR)[:-1]
        for line in read_text(str(calls)).splitlines()
        if line
    ]
    built = read_text(str(dockerfile)) if dockerfile.exists() else ""
    return proc, argvs, built


def build_args(argv: list[str]) -> dict[str, str]:
    """Args:
        argv: one ``docker build`` call.

    Returns:
        The ``--build-arg`` values of the call by name.
    """
    pairs = [argv[i + 1] for i, arg in enumerate(argv) if arg == "--build-arg"]
    return dict(pair.split("=", 1) for pair in pairs)


def base_image(dockerfile: str, args: dict[str, str]) -> str:
    """Args:
        dockerfile: the text handed to ``docker build``.
        args: the build arguments of that call.

    Returns:
        The reference the ``FROM`` line resolves to, the way the builder
        substitutes ``ARG`` values before it pulls.
    """
    values: dict[str, str] = {}
    for line in dockerfile.splitlines():
        words = line.split()
        if len(words) == 2 and words[0] == "ARG":
            name, _, default = words[1].partition("=")
            values[name] = args.get(name, default)
        elif words and words[0] == "FROM":
            return re.sub(
                r"\$\{?(\w+)\}?", lambda m: values.get(m.group(1), ""), words[1]
            )
    return ""


class TestProbeDidInnerBuild(unittest.TestCase):
    def test_the_probe_builds_from_the_ghcr_mirror_never_docker_hub(self) -> None:
        declared = load_yaml_any(str(PROBE_SERVICES), default_if_missing={})[
            PROBE_SERVICE
        ]
        with patch.dict(os.environ, GITHUB):
            expected = f"{mirror_image(declared['image'])}:{declared['version']}"

        with tempfile.TemporaryDirectory() as tmp:
            proc, argvs, dockerfile = run_probe(Path(tmp))

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        builds = [argv for argv in argvs if argv[:1] == ["build"]]
        self.assertEqual(len(builds), 1, argvs)
        resolved = base_image(dockerfile, build_args(builds[0]))
        self.assertEqual(resolved, expected)
        self.assertTrue(resolved.startswith("ghcr.io/acme/core/mirror/"), resolved)
        pulls = [argv for argv in argvs if argv[:1] == ["pull"]]
        self.assertEqual(pulls, [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
