#!/usr/bin/env python3

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

from utils.cache.files import iter_project_files

from . import PROJECT_ROOT


class TestPythonShebangs(unittest.TestCase):
    EXPECTED_PYTHON_SHEBANG = "#!/usr/bin/env python3"
    EXPECTED_ANSIBLE_MODULE_SHEBANG = "#!/usr/bin/python"

    @classmethod
    def setUpClass(cls):
        cls.repo_root = PROJECT_ROOT

    def _tracked_files(self) -> list[Path]:
        try:
            out = subprocess.check_output(
                ["git", "-C", str(self.repo_root), "ls-files", "-z"],
                stderr=subprocess.STDOUT,
            )
            rel_paths = [
                p for p in out.decode("utf-8", errors="replace").split("\0") if p
            ]
            return [self.repo_root / p for p in rel_paths]
        except Exception:
            return [Path(p) for p in iter_project_files()]

    @staticmethod
    def _first_line(path: Path) -> str:
        with path.open("rb") as fh:
            line = fh.readline(4096)
        return line.decode("utf-8", errors="replace").strip()

    @staticmethod
    def _is_ansible_custom_module(path: Path, repo_root: Path) -> bool:
        rel = path.relative_to(repo_root)
        parts = rel.parts
        # Custom Ansible modules live in a `library/` directory (per-role
        # / per-playbook layout) or in `plugins/modules/` (collection-
        # style layout). Both paths get their interpreter rewritten by
        # Ansible, so `#!/usr/bin/python` is the correct shebang.
        if parts[0] == "library" or "library" in parts[1:]:
            return True
        return len(parts) >= 2 and parts[0] == "plugins" and parts[1] == "modules"

    def test_python_shebangs_are_portable(self):
        portable_violations: list[str] = []
        ansible_module_violations: list[str] = []

        for path in self._tracked_files():
            if not path.is_file():
                continue

            first_line = self._first_line(path)
            if not first_line.startswith("#!"):
                continue

            # Only validate shebangs that invoke Python.
            if "python" not in first_line.lower():
                continue

            rel = path.relative_to(self.repo_root).as_posix()
            if self._is_ansible_custom_module(path, self.repo_root):
                if first_line != self.EXPECTED_ANSIBLE_MODULE_SHEBANG:
                    ansible_module_violations.append(f"{rel}: {first_line}")
            elif first_line != self.EXPECTED_PYTHON_SHEBANG:
                portable_violations.append(f"{rel}: {first_line}")

        if portable_violations or ansible_module_violations:
            self.fail(
                "Found invalid Python shebangs.\n\n"
                "Why this is necessary:\n"
                "- For normal Python scripts use '#!/usr/bin/env python3' so the interpreter "
                "is resolved via PATH and remains portable across distros/images.\n"
                "- For Ansible custom modules in any `library/` directory keep "
                "'#!/usr/bin/python': Ansible rewrites this interpreter path to the configured "
                "host interpreter.\n"
                "- Using '#!/usr/bin/env python3' in Ansible modules can break execution with "
                "errors like: module interpreter '/usr/bin/env python3' was not found.\n\n"
                + (
                    "Expected '#!/usr/bin/env python3' (non-library Python scripts), but found:\n- "
                    + "\n- ".join(portable_violations)
                    + "\n\n"
                    if portable_violations
                    else ""
                )
                + (
                    "Expected '#!/usr/bin/python' (Ansible custom modules in library/), but found:\n- "
                    + "\n- ".join(ansible_module_violations)
                    if ansible_module_violations
                    else ""
                )
            )


if __name__ == "__main__":
    unittest.main()
