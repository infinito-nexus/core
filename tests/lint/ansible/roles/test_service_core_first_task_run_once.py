import unittest
from pathlib import Path
import yaml

from utils.cache.files import read_text
from utils.service_registry import build_service_registry_from_roles_dir


def repo_root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "pyproject.toml").is_file():
            return candidate
    raise AssertionError("Repository root not found from test path.")


REPO_ROOT = repo_root()

RUN_ONCE_TASK = {"include_tasks": "utils/once/flag.yml"}


def load_service_registry():
    return build_service_registry_from_roles_dir(REPO_ROOT / "roles")


def unique_roles(registry):
    seen = set()
    for entry in registry.values():
        if "canonical" in entry:
            continue
        role = entry.get("role")
        if role and role not in seen:
            seen.add(role)
            yield role


RECURSION_HINT = (
    "Service roles discovered from role-local services metadata are loaded "
    "dynamically via "
    "load_app.yml, which checks the run_once_<role> flag before loading a role. "
    "If tasks/01_core.yml does not set this flag as its very first task, the flag "
    "may be absent when a second load attempt is evaluated, causing load_app.yml to "
    "include the role again and triggering infinite recursion."
)

MAIN_SCHEMA_HINT = (
    "tasks/main.yml must load 01_core.yml with a run_once guard so that roles "
    "included directly (not via load_app.yml) are also protected against duplicate "
    "execution. Required schema:\n"
    "  - include_tasks: 01_core.yml\n"
    "    when: run_once_<role_slug> is not defined"
)


def role_slug(role):
    return role.replace("-", "_")


class TestServiceCoreFirstTaskRunOnce(unittest.TestCase):
    """
    For every discovered shared service role:
      1. roles/<role>/tasks/01_core.yml must exist.
      2. Its first task must be: - include_tasks: utils/once/flag.yml
      3. tasks/main.yml must include 01_core.yml with the correct run_once when-guard.
    """

    def setUp(self):
        self.project_root = REPO_ROOT
        self.registry = load_service_registry()

    def _core_path(self, role):
        return self.project_root / "roles" / role / "tasks" / "01_core.yml"

    def _main_path(self, role):
        return self.project_root / "roles" / role / "tasks" / "main.yml"

    def test_01_core_exists(self):
        missing = []
        for role in unique_roles(self.registry):
            if not self._core_path(role).is_file():
                missing.append(role)
        if missing:
            self.fail(
                "roles missing tasks/01_core.yml:\n"
                + "\n".join(f"  {r}" for r in sorted(missing))
                + f"\n\nWhy this matters:\n{RECURSION_HINT}"
            )

    def test_first_task_is_run_once_flag(self):
        violations = []
        for role in unique_roles(self.registry):
            path = self._core_path(role)
            if not path.is_file():
                continue  # covered by test_01_core_exists

            try:
                tasks = yaml.safe_load(read_text(str(path)))
            except yaml.YAMLError as e:
                self.fail(f"Failed to parse {path}: {e}")

            if not isinstance(tasks, list) or not tasks:
                violations.append(f"{role}: tasks/01_core.yml is empty or not a list")
                continue

            first = tasks[0]
            if first != RUN_ONCE_TASK:
                violations.append(
                    f"{role}: first task is {first!r}, expected {RUN_ONCE_TASK!r}"
                )

        if violations:
            self.fail(
                "tasks/01_core.yml must start with '- include_tasks: utils/once/flag.yml':\n"
                + "\n".join(f"  {v}" for v in violations)
                + f"\n\nWhy this matters:\n{RECURSION_HINT}"
            )

    def test_main_yml_loads_core_with_run_once_guard(self):
        violations = []
        for role in unique_roles(self.registry):
            main_path = self._main_path(role)
            if not main_path.is_file():
                violations.append(f"{role}: tasks/main.yml is missing")
                continue

            try:
                tasks = yaml.safe_load(read_text(str(main_path)))
            except yaml.YAMLError as e:
                self.fail(f"Failed to parse {main_path}: {e}")

            if not isinstance(tasks, list):
                violations.append(f"{role}: tasks/main.yml is not a list")
                continue

            expected_when = f"run_once_{role_slug(role)} is not defined"
            core_task = next(
                (
                    t
                    for t in tasks
                    if isinstance(t, dict) and t.get("include_tasks") == "01_core.yml"
                ),
                None,
            )

            if core_task is None:
                violations.append(
                    f"{role}: tasks/main.yml has no '- include_tasks: 01_core.yml' entry"
                )
                continue

            actual_when = core_task.get("when", "")
            if actual_when != expected_when:
                violations.append(
                    f"{role}: when is '{actual_when}', expected '{expected_when}'"
                )

        if violations:
            self.fail(
                "tasks/main.yml does not correctly load 01_core.yml:\n"
                + "\n".join(f"  {v}" for v in violations)
                + f"\n\nWhy this matters:\n{MAIN_SCHEMA_HINT}"
            )


if __name__ == "__main__":
    unittest.main()
