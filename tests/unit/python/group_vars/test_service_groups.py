import re
import unittest
from pathlib import Path
from typing import ClassVar

from jinja2 import StrictUndefined, meta
from jinja2.nativetypes import NativeEnvironment

from plugins.filter.get.category_entries import get_category_entries
from plugins.lookup.unit_name import LookupModule
from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml

_DAEMONS = Path(PROJECT_ROOT) / "group_vars" / "all" / "06_daemons.yml"
_ROLES = str(Path(PROJECT_ROOT) / "roles")
_VERSION_SUFFIX = ".1.2.3.infinito.nexus"
_FIXED = {
    "SOFTWARE_DOMAIN": "infinito.nexus",
    "SYS_SERVICE_VERSION_SUFFIX": _VERSION_SUFFIX,
}


class _Templar:
    available_variables: ClassVar[dict] = dict(_FIXED)

    def template(self, value, **_kwargs):
        return value


def _unit_names(*terms, **kwargs):
    plugin = LookupModule()
    plugin._templar = _Templar()
    plugin.set_options = lambda *args, **kw: None
    return plugin.run(list(terms), **kwargs)


def _query(name, *terms, **kwargs):
    if name != "unit_name":
        raise AssertionError(f"unexpected query({name!r})")
    return _unit_names(*terms, **kwargs)


def _lookup(name, *terms, **kwargs):
    return ",".join(_query(name, *terms, **kwargs))


def _entries(prefix):
    return get_category_entries(prefix, roles_path=_ROLES)


class TestServiceGroupsMatchUnitNames(unittest.TestCase):
    env: ClassVar[NativeEnvironment]
    sources: ClassVar[dict]
    rendered: ClassVar[dict]

    @classmethod
    def setUpClass(cls):
        cls.env = NativeEnvironment(undefined=StrictUndefined)
        cls.env.filters["get_category_entries"] = _entries
        cls.env.filters["regex_replace"] = lambda value, pattern, repl: re.sub(
            pattern, repl, value
        )
        cls.env.globals.update(query=_query, lookup=_lookup)
        cls.sources = load_yaml(_DAEMONS)
        cls.rendered = dict(_FIXED)

    def _render(self, name):
        if name in self.rendered:
            return self.rendered[name]
        source = str(self.sources[name]).strip()
        for dependency in meta.find_undeclared_variables(self.env.parse(source)):
            if dependency in self.sources or dependency in _FIXED:
                self._render(dependency)
        value = self.env.from_string(source).render(**self.rendered)
        self.rendered[name] = value
        return value

    def _expected(self, *prefixes):
        ids = [role for prefix in prefixes for role in _entries(prefix)]
        return sorted(_unit_names(*ids)) if ids else []

    def test_backup_group_names_the_installed_backup_units(self):
        self.assertEqual(
            self._render("SYS_SERVICE_GROUP_BACKUPS"),
            self._expected("sys-ctl-bkp-", "svc-bkp-"),
        )

    def test_cleanup_group_names_the_installed_cleanup_units(self):
        self.assertEqual(
            self._render("SYS_SERVICE_GROUP_CLEANUP"),
            self._expected("sys-ctl-cln-"),
        )

    def test_repair_group_names_the_installed_repair_units(self):
        self.assertEqual(
            self._render("SYS_SERVICE_GROUP_REPAIR"),
            self._expected("sys-ctl-rpr-"),
        )

    def test_optimization_group_names_the_installed_optimizer_units(self):
        self.assertEqual(
            self._render("SYS_SERVICE_GROUP_OPTIMIZATION"),
            self._expected("svc-opt-"),
        )

    def test_a_category_without_roles_renders_an_empty_group(self):
        self.assertEqual(self._render("SYS_SERVICE_GROUP_MAINTANANCE"), [])

    def test_manipulation_group_is_the_union_of_all_groups(self):
        self.assertEqual(
            self._render("SYS_SERVICE_GROUP_MANIPULATION"),
            sorted(
                self._expected("sys-ctl-bkp-", "svc-bkp-")
                + self._expected("sys-ctl-cln-")
                + self._expected("sys-ctl-rpr-")
                + self._expected("svc-opt-")
            ),
        )

    def test_named_units_are_members_of_their_group(self):
        membership = {
            "SYS_SERVICE_CLEANUP_BACKUPS": "SYS_SERVICE_GROUP_CLEANUP",
            "SYS_SERVICE_CLEANUP_DISC_SPACE": "SYS_SERVICE_GROUP_CLEANUP",
            "SYS_SERVICE_BACKUP_VOLUME_2_LOCAL": "SYS_SERVICE_GROUP_BACKUPS",
            "SYS_SERVICE_REPAIR_CONTAINER_SOFT": "SYS_SERVICE_GROUP_REPAIR",
            "SYS_SERVICE_OPTIMIZE_DRIVE": "SYS_SERVICE_GROUP_OPTIMIZATION",
        }
        for unit, group in membership.items():
            with self.subTest(unit=unit):
                self.assertIn(self._render(unit), self._render(group))


if __name__ == "__main__":
    unittest.main()
