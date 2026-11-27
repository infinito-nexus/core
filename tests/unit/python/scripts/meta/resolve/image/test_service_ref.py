from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_any
from utils.docker.mirror import mirror_image
from utils.roles.mapping import ROLE_FILE_META_SERVICES

RESOLVER = PROJECT_ROOT / "scripts" / "meta" / "resolve" / "image" / "service_ref.sh"
ROLE = "svc-db-openldap"
SERVICE = "openldap"
STRIPPED = (
    "OWNER",
    "GITHUB_REPOSITORY_OWNER",
    "GITHUB_REPOSITORY",
    "REPO_PREFIX",
    "INFINITO_IMAGE_REPOSITORY",
)
GITHUB = {
    "GITHUB_REPOSITORY": "Acme/Core",
    "GITHUB_REPOSITORY_OWNER": "Acme",
    "INFINITO_GHCR_MIRROR_PREFIX": "mirror",
}
FAKE_DOCKER = """#!/usr/bin/env bash
printf '%s\\n' "$*" >>"${FAKE_DOCKER_CALLS}"
exit 1
"""


def resolve(tmp: Path, **overrides: str) -> tuple[subprocess.CompletedProcess, str]:
    """Args:
        tmp: scratch directory outside any git checkout, used as cwd.
        overrides: environment entries on top of the stripped environment.

    Returns:
        The resolver's process for ``mirror-only`` and every docker call it made.
    """
    bin_dir = tmp / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(FAKE_DOCKER, encoding="utf-8")
    docker.chmod(0o755)
    calls = tmp / "calls"
    calls.touch()
    env = {k: v for k, v in os.environ.items() if k not in STRIPPED}
    env.update(
        {
            "BASH_ENV": "",
            "PATH": f"{bin_dir}{os.pathsep}{env['PATH']}",
            "FAKE_DOCKER_CALLS": str(calls),
            "GIT_CEILING_DIRECTORIES": str(tmp.parent),
        }
    )
    env.update(overrides)
    proc = subprocess.run(
        ["bash", str(RESOLVER), ROLE, SERVICE, "mirror-only"],
        cwd=tmp,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc, read_text(str(calls))


class TestServiceRefMirrorOnly(unittest.TestCase):
    def test_prints_the_mirror_ref_without_asking_docker(self) -> None:
        declared = load_yaml_any(
            str(PROJECT_ROOT / "roles" / ROLE / ROLE_FILE_META_SERVICES),
            default_if_missing={},
        )[SERVICE]
        with patch.dict(os.environ, GITHUB):
            expected = f"{mirror_image(declared['image'])}:{declared['version']}"
        with tempfile.TemporaryDirectory() as tmp:
            proc, calls = resolve(Path(tmp), **GITHUB)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), expected)
        self.assertEqual(calls, "")

    def test_an_unresolvable_namespace_fails_instead_of_the_upstream(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proc, _ = resolve(Path(tmp), INFINITO_GHCR_MIRROR_PREFIX="mirror")
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, "")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
