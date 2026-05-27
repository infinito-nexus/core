import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_anywhere, line_has_rule
from utils.cache.files import iter_project_files, read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_TASKS_MAIN


class RunOnceSchemaTest(unittest.TestCase):
    """
    Ensure that any occurrence of 'run_once_' in roles/*/tasks/main.yml
    matches 'run_once_' + (role_name with '-' replaced by '_'),
    unless explicitly deactivated with:
      # nocheck: run-once

    Exception (per-when item):
      If the *same line* that contains the run_once_ condition also
      carries a ``# nocheck: run-once-suffix`` marker, that specific
      condition is ignored by this test.

    Only block-level 'when' conditions in main.yml are considered. The
    unified suppression-marker grammar is documented at
    ``docs/contributing/actions/testing/suppression.md``.
    """

    @staticmethod
    def _run_once_vars_from_when(when_clause):
        if isinstance(when_clause, list):
            return [
                w
                for w in when_clause
                if isinstance(w, str) and w.startswith("run_once_")
            ]
        if isinstance(when_clause, str):
            return [when_clause] if when_clause.startswith("run_once_") else []
        return []

    @staticmethod
    def _line_has_suffix_opt_out(content: str, var: str) -> bool:
        """Return True iff the list-item line that contains *var* carries
        a ``run-once-suffix`` suppression marker.
        """
        line_re = re.compile(
            rf"^.*-\s*{re.escape(var)}\b.*$",
            flags=re.IGNORECASE | re.MULTILINE,
        )
        return any(
            line_has_rule(match.group(0), "run-once-suffix")
            for match in line_re.finditer(content)
        )

    def test_run_once_suffix_matches_role(self):
        from . import PROJECT_ROOT

        project_root = str(PROJECT_ROOT)
        violations = []

        roles_prefix = str(Path(project_root) / "roles") + "/"
        main_files = (
            p
            for p in iter_project_files(extensions=(".yml",))
            if p.startswith(roles_prefix) and p.endswith(f"/{ROLE_FILE_TASKS_MAIN}")
        )
        for filepath in main_files:
            role_name = Path(filepath).parts[-3]
            expected_suffix = role_name.lower().replace("-", "_")

            try:
                content = read_text(filepath)
            except (OSError, UnicodeDecodeError) as e:
                violations.append(f"{filepath}: read error: {e}")
                continue

            if is_suppressed_anywhere(content.splitlines(), "run-once"):
                continue

            try:
                data = load_yaml_str(content)
            except Exception as e:
                violations.append(f"{filepath}: YAML parse error: {e}")
                continue

            if not isinstance(data, list):
                continue

            for task in data:
                # Only check top-level blocks
                if not (isinstance(task, dict) and "block" in task):
                    continue

                when_clause = task.get("when")
                if not when_clause:
                    continue

                run_once_vars = self._run_once_vars_from_when(when_clause)
                if not run_once_vars:
                    continue

                for var in run_once_vars:
                    if self._line_has_suffix_opt_out(content, var):
                        continue

                    # strip any ' is not defined' etc.
                    suffix = var[len("run_once_") :].split()[0]
                    if suffix != expected_suffix:
                        violations.append(
                            f"{filepath}: found block-level {var}, expected run_once_{expected_suffix}"
                        )

        if violations:
            self.fail("Invalid run_once_ suffixes found:\n" + "\n".join(violations))


if __name__ == "__main__":
    unittest.main()
