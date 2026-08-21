"""Lint guard: never hard-code the compose container name of one distro.

``INFINITO_CONTAINER`` is derived from ``INFINITO_DISTRO`` by
``utils/env/handlers/infinito/container.py`` and exported into every script
by ``scripts/meta/env/load.sh``. A literal ``infinito_nexus_<distro>`` pins
the line to one checkout shape: it misses every other distro, the
runner-prefixed ``infinito_<project>_nexus_<distro>`` form, and any
``custom.env`` override. The guarded branch then never fires, with nothing
failing to make that visible. Read ``"${INFINITO_CONTAINER}"`` instead.

Distro-agnostic spellings carry no literal distro and stay allowed: the
``^infinito_nexus_`` prefix match in
``scripts/system/network/docker/stack_refresh.sh`` and the slug-composed
name in ``scripts/system/worktree/up.sh``. A comment line and the hint text
of a ``${VAR:?...}`` expansion name an example in prose rather than a value,
so both are skipped.

Per-line opt-out: ``# nocheck: hardcoded-container`` on the offending line
or the one above it.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import PROJECT_ROOT, iter_project_files, read_text
from utils.distros import FILE_META_DISTROS, distro_names

_RULE = "hardcoded-container"
_CONTAINER = re.compile(r"infinito_\w*nexus_(?:" + "|".join(distro_names()) + r")\b")


class TestNoHardcodedContainerName(unittest.TestCase):
    def test_container_name_is_read_from_the_env_spot(self) -> None:
        offenders: list[str] = []
        for path_str in iter_project_files(
            extensions=(".sh", ".yml"),
            exclude_tests=True,
            exclude_dirs=("docs",),
        ):
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            lines = read_text(path_str).splitlines()
            for lineno, line in enumerate(lines, 1):
                match = _CONTAINER.search(line)
                if match is None:
                    continue
                if line.lstrip().startswith("#") or ":?" in line[: match.start()]:
                    continue
                if is_suppressed_at(lines, lineno, _RULE):
                    continue
                offenders.append(f"{rel}:{lineno}: {line.strip()}")

        if offenders:
            self.fail(
                f"{len(offenders)} container name(s) hard-coded to a single "
                f"distro declared in {FILE_META_DISTROS}. The name is derived "
                'per distro; read "${INFINITO_CONTAINER}" (exported by '
                "scripts/meta/env/load.sh) so the line works on every distro, "
                f"or mark a genuinely single-distro line `# nocheck: {_RULE}`."
                "\n" + "\n".join(f"  - {o}" for o in offenders)
            )


if __name__ == "__main__":
    unittest.main()
