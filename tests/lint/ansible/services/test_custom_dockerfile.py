"""Couple role Dockerfiles to ``services.<key>.custom`` declarations.

Rule
====
Both directions must hold per role:

* A service declaring ``custom:`` (locally-built image) requires a
  ``Dockerfile``/``Dockerfile.j2`` in the role — otherwise the resolved
  ``*_custom`` reference points at an image nothing ever builds.
* A role shipping a ``Dockerfile`` must declare ``custom:`` on at least
  one service in ``meta/services.yml`` — otherwise the local build is
  deployed under an upstream tag (shadowing the real upstream image on
  the host) or through an ad-hoc ``image=`` override, both of which hide
  the build from config consumers such as the backup image matching.

Per-role opt-out
================
Add ``# nocheck: dockerfile-custom`` anywhere in the role's
``meta/services.yml``.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

from utils.cache.files import iter_project_files, read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

_RULE = "dockerfile-custom"
_ROLES_PREFIX = "roles/"


def _custom_services(services_path):
    try:
        data = load_yaml_any(services_path, default_if_missing={})
    except yaml.YAMLError:
        return []
    if not isinstance(data, dict):
        return []
    return sorted(
        key
        for key, entry in data.items()
        if isinstance(entry, dict) and entry.get("custom")
    )


class TestCustomDockerfileCoupling(unittest.TestCase):
    def test_dockerfile_and_custom_declarations_match(self) -> None:
        dockerfiles: dict[str, list[str]] = {}
        services_files: dict[str, str] = {}
        for path in iter_project_files(exclude_tests=True):
            rel = Path(path).relative_to(PROJECT_ROOT).as_posix()
            if not rel.startswith(_ROLES_PREFIX):
                continue
            parts = rel.split("/")
            if len(parts) < 3:
                continue
            role = parts[1]
            if Path(rel).name.startswith("Dockerfile"):
                dockerfiles.setdefault(role, []).append("/".join(parts[2:]))
            elif rel == f"{_ROLES_PREFIX}{role}/{ROLE_FILE_META_SERVICES}":
                services_files[role] = path

        findings: list[str] = []
        for role in sorted(set(dockerfiles) | set(services_files)):
            services_path = services_files.get(role)
            if services_path and f"# nocheck: {_RULE}" in read_text(services_path):
                continue
            role_dockerfiles = sorted(dockerfiles.get(role, []))
            custom = _custom_services(services_path) if services_path else []
            rel = f"{_ROLES_PREFIX}{role}"
            if custom and not role_dockerfiles:
                findings.append(
                    f"- {rel}: services {custom} declare custom: but the role "
                    "ships no Dockerfile"
                )
            if role_dockerfiles and not custom:
                findings.append(
                    f"- {rel}: role ships {role_dockerfiles} but no service in "
                    "meta/services.yml declares custom:"
                )

        if findings:
            self.fail(
                "Dockerfile/custom coupling violated (locally-built images "
                "must be declared via services.<key>.custom, and every "
                "custom declaration needs a Dockerfile). Opt out with "
                f"`# nocheck: {_RULE}` in the role's meta/services.yml:\n"
                + "\n".join(sorted(findings))
            )


if __name__ == "__main__":
    unittest.main()
