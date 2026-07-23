"""Lint guard: env handlers MUST NOT use ``utils.cache.yaml``.

The handlers under ``utils/env/handlers/`` feed the ``.env`` generation,
which bootstraps fresh hosts before PyYAML is installed; importing the
YAML cache there breaks the bootstrap. Read SPOT files with
``utils.cache.files.read_text`` and a stdlib line parse instead (see
``utils/storage/nfs.py`` for the canonical pattern).

Suppress on a per-line basis with a same-line ``# nocheck: <reason>``
marker only when the handler provably never runs in the bootstrap path.
"""

from __future__ import annotations

import re
import unittest
from dataclasses import dataclass
from pathlib import Path

from utils.cache.files import iter_project_files, read_text

from . import PROJECT_ROOT

_HANDLERS_DIR = PROJECT_ROOT / "utils" / "env" / "handlers"
_YAML_CACHE_RE = re.compile(r"\butils\.cache\.yaml\b")
_NOCHECK_RE = re.compile(r"#\s*nocheck\b")


@dataclass(frozen=True)
class Violation:
    file: str
    line_no: int
    detail: str


def _scan_file(path: Path) -> list[Violation]:
    violations: list[Violation] = []
    rel = path.relative_to(PROJECT_ROOT).as_posix()
    for idx, raw in enumerate(read_text(str(path)).splitlines(), 1):
        if _NOCHECK_RE.search(raw):
            continue
        if _YAML_CACHE_RE.search(raw):
            violations.append(Violation(rel, idx, raw.strip()))
    return violations


class TestNoYamlCacheInEnvHandlers(unittest.TestCase):
    def test_env_handlers_dont_use_yaml_cache(self) -> None:
        targets = sorted(
            Path(p)
            for p in iter_project_files(extensions=(".py",))
            if Path(p).is_relative_to(_HANDLERS_DIR)
        )
        self.assertTrue(targets, "no handler modules found to scan")
        all_violations: list[Violation] = []
        for path in targets:
            all_violations.extend(_scan_file(path))
        if all_violations:
            lines = [
                f"utils.cache.yaml used in env handlers "
                f"({len(all_violations)} violation(s)):",
                "",
                "Env handlers feed the .env generation, which bootstraps fresh hosts before PyYAML is initialised - utils.cache.yaml is unavailable at that point. Use utils.cache.files.read_text with a stdlib line parse instead (canonical pattern: utils/storage/nfs.py). Suppress per line with `# nocheck: <reason>` only when the handler provably never runs in the bootstrap path.",
                "",
                "Offenders:",
            ]
            lines.extend(f"  {v.file}:{v.line_no}: {v.detail}" for v in all_violations)
            self.fail("\n".join(lines))


if __name__ == "__main__":
    unittest.main()
