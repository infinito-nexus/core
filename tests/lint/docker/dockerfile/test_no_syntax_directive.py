"""Lint guard: no Dockerfile may carry a ``# syntax=`` parser directive.

The directive tells BuildKit to fetch an external frontend image (e.g.
``docker/dockerfile:1``) from Docker Hub and hand the Dockerfile to it for
parsing. Three reasons this project refuses it:

* **Not future-proof.** ``docker/dockerfile:1`` floats to the newest 1.x
  frontend, so a Hub-side release can change parse semantics of an unchanged
  Dockerfile. Pinning a patch version instead only trades that for a stale
  pin nobody bumps.
* **Podman incompatible.** Podman builds through Buildah, which has no
  frontend dispatch at all, so the directive is silently discarded. Any
  Dockerfile relying on a frontend-only feature builds under Docker and
  breaks under Podman, and the directive hides that asymmetry.
* **Flaky CI.** The frontend pull is a build-time network dependency on
  docker.io. When Hub is down, rate-limits the runner, or the runner is
  air-gapped, the build fails before the first instruction runs.

Dockerfiles must therefore stay within what the local builder understands,
Docker and Buildah alike.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.cache.files import iter_project_files, read_text

from . import PROJECT_ROOT

_SYNTAX_DIRECTIVE_RE = re.compile(r"^\s*#\s*syntax\s*=", re.IGNORECASE)


def _is_dockerfile(path: str) -> bool:
    name = Path(path).name.lower()
    return name.startswith("dockerfile") or ".dockerfile" in name


def _collect_violations() -> list[str]:
    violations: list[str] = []
    for path in sorted(iter_project_files()):
        if not _is_dockerfile(path):
            continue
        relative = Path(path).relative_to(PROJECT_ROOT).as_posix()
        violations.extend(
            f"{relative}:{lineno}: {line.strip()}"
            for lineno, line in enumerate(read_text(path).splitlines(), start=1)
            if _SYNTAX_DIRECTIVE_RE.match(line)
        )
    return violations


class TestDockerfileNoSyntaxDirective(unittest.TestCase):
    """Fail when a Dockerfile pins an external BuildKit frontend."""

    def test_no_dockerfile_declares_a_syntax_frontend(self) -> None:
        violations = _collect_violations()

        self.assertFalse(
            violations,
            "The following Dockerfiles declare a '# syntax=' parser directive.\n"
            "It pins an external BuildKit frontend, which is not future-proof "
            "(the tag floats), is ignored by Podman/Buildah, and turns every "
            "build into a docker.io network dependency that breaks CI whenever "
            "Docker Hub is unavailable.\n"
            "Remove the directive and keep the Dockerfile within the feature set "
            "of the local builder:\n\n" + "\n".join(f"  {v}" for v in violations),
        )


if __name__ == "__main__":
    unittest.main()
