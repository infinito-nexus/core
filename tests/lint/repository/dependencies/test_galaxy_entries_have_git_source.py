"""Lint: every collection in ``requirements/requirements.galaxy.yml``
MUST also be declared as a git source in
``requirements/requirements.git.yml``.

``scripts/install/ansible.sh`` falls back to the git requirements file
when ``galaxy.ansible.com`` is unreachable, so the fallback only helps
while it stays feature-equivalent. A collection present only in the
Galaxy file is either skipped by the fallback or resolved against
Galaxy again as a transitive dependency, which fails ``make install``
on the very outage the fallback exists for.

Suppress with ``# nocheck: galaxy-git-parity`` on the entry's line or
the line above it in ``requirements.galaxy.yml``. Reserved for
collections that publish no usable git remote.
"""

from __future__ import annotations

import re
import unittest

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml

from . import PROJECT_ROOT

_RULE = "galaxy-git-parity"

_GALAXY_REQ = "requirements/requirements.galaxy.yml"
_GIT_REQ = "requirements/requirements.git.yml"

_NAME_RE = re.compile(r"^\s*-\s+name:\s*(\S+)")


class TestGalaxyEntriesHaveGitSource(unittest.TestCase):
    def test_every_galaxy_collection_has_a_git_source(self) -> None:
        git_names = {
            str(entry["name"])
            for entry in load_yaml(PROJECT_ROOT / _GIT_REQ)["collections"]
        }
        lines = read_text(str(PROJECT_ROOT / _GALAXY_REQ)).splitlines()

        offenders: list[str] = []
        for no, line in enumerate(lines, start=1):
            match = _NAME_RE.match(line)
            if not match:
                continue
            name = match.group(1).strip("\"'")
            if name in git_names:
                continue
            if is_suppressed_at(lines, no, _RULE):
                continue
            offenders.append(f"{_GALAXY_REQ}:{no}: {name}")

        if offenders:
            self.fail(
                f"{len(offenders)} collection(s) without a git fallback "
                f"source. A Galaxy outage takes down `make install` for "
                f"these. Add a `type: git` entry to {_GIT_REQ}, or mark a "
                f"legitimate exception with `# nocheck: {_RULE}`:\n"
                + "\n".join(f"  - {o}" for o in offenders)
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
