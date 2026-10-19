import importlib
import tempfile
import unittest
from pathlib import Path


class TestVersionLookup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.plugin_module = importlib.import_module("plugins.lookup.version")
            cls.LookupModule = cls.plugin_module.LookupModule
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest(
                "Could not import lookup plugin 'plugins.lookup.version'. "
                "Make sure tests run with repo root on PYTHONPATH."
            ) from exc
        except Exception as exc:
            raise unittest.SkipTest(f"Failed importing lookup plugin: {exc}") from exc

        # Ensure ansible is importable (plugin depends on it)
        try:
            import ansible  # noqa: F401
        except Exception as exc:
            raise unittest.SkipTest(
                f"Ansible not available for unit tests: {exc}"
            ) from exc

    def _run_with_repo_layout(self, pyproject_content: str | None, terms=()):
        """
        Creates a temporary repo-like layout:
          <tmp>/pyproject.toml              (optional)
        Then executes the lookup plugin with PROJECT_ROOT pointing at <tmp>.
        """
        plugin_mod = self.plugin_module
        original_root = plugin_mod.PROJECT_ROOT

        with tempfile.TemporaryDirectory() as tmp:
            if pyproject_content is not None:
                pyproject_path = str(Path(tmp) / "pyproject.toml")
                with Path(pyproject_path).open("w", encoding="utf-8") as f:
                    f.write(pyproject_content)

            plugin_mod.PROJECT_ROOT = Path(tmp)

            try:
                plugin = self.LookupModule()
                return plugin.run(list(terms))
            finally:
                plugin_mod.PROJECT_ROOT = original_root

    def test_reads_project_version(self):
        result = self._run_with_repo_layout(
            """
[project]
name = "demo"
version = "1.2.3"
"""
        )
        self.assertEqual(result, ["1.2.3"])

    def test_falls_back_to_poetry_version(self):
        result = self._run_with_repo_layout(
            """
[tool.poetry]
name = "demo"
version = "2.3.4"
"""
        )
        self.assertEqual(result, ["2.3.4"])

    def test_reads_the_exact_pin_of_a_dependency(self):
        result = self._run_with_repo_layout(
            """
[project]
name = "demo"
version = "1.2.3"
dependencies = ["bcrypt", "backup-docker-to-local==7.1.1", "PyYAML"]
""",
            terms=["backup-docker-to-local"],
        )
        self.assertEqual(result, ["7.1.1"])

    def test_a_dependency_without_an_exact_pin_raises(self):
        from ansible.errors import AnsibleError

        for dependencies in ('["backup-docker-to-local>=7"]', '["bcrypt"]'):
            with (
                self.subTest(dependencies=dependencies),
                self.assertRaises(AnsibleError),
            ):
                self._run_with_repo_layout(
                    f"""
[project]
name = "demo"
version = "1.2.3"
dependencies = {dependencies}
""",
                    terms=["backup-docker-to-local"],
                )

    def test_more_than_one_term_raises(self):
        from ansible.errors import AnsibleError

        with self.assertRaises(AnsibleError):
            self._run_with_repo_layout(
                """
[project]
name = "demo"
version = "1.2.3"
dependencies = ["a==1", "b==2"]
""",
                terms=["a", "b"],
            )

    def test_missing_pyproject_raises(self):
        from ansible.errors import AnsibleError

        with self.assertRaises(AnsibleError):
            self._run_with_repo_layout(pyproject_content=None)

    def test_missing_version_raises(self):
        from ansible.errors import AnsibleError

        with self.assertRaises(AnsibleError):
            self._run_with_repo_layout(
                """
[project]
name = "demo"
# no version here
"""
            )


if __name__ == "__main__":
    unittest.main()
