"""Focused unit tests for ``utils.cache.domains``.

`get_merged_domains` is a thin derivation on top of
`get_merged_applications` plus the
`plugins.filter.canonical_domains_map` filter. We pin: cache-keying
behaviour, the missing-DOMAIN_PRIMARY validation, and the dispatch to
the upstream applications view.
"""

from __future__ import annotations

import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.cache import _reset_cache_for_tests
from utils.cache import domains as cache_domains
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_META_USERS

from . import PROJECT_ROOT


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content), encoding="utf-8")


def _seed_minimal_role(tmp: Path) -> Path:
    role = tmp / "roles" / "web-app-foo"
    _write(
        role / ROLE_FILE_META_SERVICES,
        """
        server:
          domains:
            canonical:
              - foo.{{ DOMAIN_PRIMARY }}
            aliases: []
        """,
    )
    _write(role / ROLE_FILE_META_USERS, "users: {}\n")
    return tmp / "roles"


class TestMissingPrimaryDomain(unittest.TestCase):
    def setUp(self) -> None:
        _reset_cache_for_tests()

    def test_raises_when_domain_primary_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            roles = _seed_minimal_role(Path(tmp))
            with self.assertRaisesRegex(ValueError, "DOMAIN_PRIMARY"):
                cache_domains.get_merged_domains(
                    variables={}, roles_dir=roles, templar=None
                )

    def test_falls_back_to_system_email_domain(self):
        # Pure-python smoke: when DOMAIN_PRIMARY is absent but
        # SYSTEM_EMAIL_DOMAIN is set, the function should NOT raise.
        # The actual canonical-domains-map computation is exercised
        # indirectly via get_merged_applications; we patch it out so
        # this stays an isolated unit test of the dispatch code path.
        with tempfile.TemporaryDirectory() as tmp:
            roles = _seed_minimal_role(Path(tmp))
            with patch(
                "utils.cache.applications.get_merged_applications",
                return_value={},
            ):
                result = cache_domains.get_merged_domains(
                    variables={"SYSTEM_EMAIL_DOMAIN": "infinito.example"},
                    roles_dir=roles,
                    templar=None,
                )
            self.assertIsInstance(result, dict)


class TestCachingPerVariablesSignature(unittest.TestCase):
    def setUp(self) -> None:
        _reset_cache_for_tests()

    def test_caches_result_for_identical_variables(self):
        # Patch out the heavy call so this is a pure cache-behaviour test.
        with tempfile.TemporaryDirectory() as tmp:
            roles = _seed_minimal_role(Path(tmp))
            with patch(
                "utils.cache.applications.get_merged_applications",
                return_value={},
            ) as mocked:
                first = cache_domains.get_merged_domains(
                    variables={"DOMAIN_PRIMARY": "infinito.example"},
                    roles_dir=roles,
                    templar=None,
                )
                second = cache_domains.get_merged_domains(
                    variables={"DOMAIN_PRIMARY": "infinito.example"},
                    roles_dir=roles,
                    templar=None,
                )
            # Same cache key -> upstream MUST only be called once.
            self.assertEqual(mocked.call_count, 1)
            self.assertEqual(first, second)

    def test_different_domain_primary_misses_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            roles = _seed_minimal_role(Path(tmp))
            with patch(
                "utils.cache.applications.get_merged_applications",
                return_value={},
            ) as mocked:
                cache_domains.get_merged_domains(
                    variables={"DOMAIN_PRIMARY": "a.example"},
                    roles_dir=roles,
                    templar=None,
                )
                cache_domains.get_merged_domains(
                    variables={"DOMAIN_PRIMARY": "b.example"},
                    roles_dir=roles,
                    templar=None,
                )
            self.assertEqual(mocked.call_count, 2)


class TestResetClearsDomainsCache(unittest.TestCase):
    def test_reset_evicts_cached_entry(self):
        _reset_cache_for_tests()
        with tempfile.TemporaryDirectory() as tmp:
            roles = _seed_minimal_role(Path(tmp))
            with patch(
                "utils.cache.applications.get_merged_applications",
                return_value={},
            ):
                cache_domains.get_merged_domains(
                    variables={"DOMAIN_PRIMARY": "infinito.example"},
                    roles_dir=roles,
                    templar=None,
                )
                # Cache MUST hold one entry now.
                self.assertEqual(len(cache_domains._MERGED_DOMAINS_CACHE), 1)
                _reset_cache_for_tests()
                # Cache MUST be empty after the orchestrator runs.
                self.assertEqual(len(cache_domains._MERGED_DOMAINS_CACHE), 0)


class TestImportableWithoutAnsible(unittest.TestCase):
    """`utils.cache.domains` MUST stay ansible-free at import time so
    callers in CLI/runner-host paths can pull the module without
    needing ansible. Calling `get_merged_domains` requires ansible
    transitively (via `canonical_domains_map`) and is NOT pinned here
    — the import-only invariant is what matters for the
    ansible-less host. Subprocess isolation avoids the in-process
    sys.modules / namespace-package hazards that bit earlier shims.
    """

    def test_module_imports_without_ansible(self):
        import subprocess

        repo_root = PROJECT_ROOT
        snippet = (
            "import sys\n"
            f"sys.path.insert(0, {str(repo_root)!r})\n"
            "class _Block:\n"
            "    def find_spec(self, name, path=None, target=None):\n"
            "        if name == 'ansible' or name.startswith('ansible.'):\n"
            "            raise ImportError(f'blocked: {name}')\n"
            "        return None\n"
            "sys.meta_path.insert(0, _Block())\n"
            "from utils.cache.domains import get_merged_domains\n"
            "assert callable(get_merged_domains)\n"
            "print('OK')\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", snippet],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
            timeout=60,
            check=False,
        )
        self.assertEqual(
            result.returncode,
            0,
            msg=f"stderr=\n{result.stderr}\nstdout=\n{result.stdout}",
        )
        self.assertIn("OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
