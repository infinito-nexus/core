from __future__ import annotations

import importlib.util
import sys
from unittest import TestCase, main, mock

from ansible.errors import AnsibleError

from . import PROJECT_ROOT


def _load_module():
    path = (
        PROJECT_ROOT
        / "roles"
        / "sys-ctl-hlth-runtime"
        / "lookup_plugins"
        / "php_hardened_services.py"
    )
    spec = importlib.util.spec_from_file_location("php_hardened_services_lookup", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = _load_module()

HARDENING = {
    "type": "config",
    "source": "{{ FILE_PHP_HARDENING_INI }}",
    "mounts": [
        {"service": "nextcloud", "target": "/usr/local/etc/php/conf.d/zz.ini"},
    ],
}


class TestHardenedServices(TestCase):
    def test_lists_every_mounting_service_once(self):
        entry = dict(
            HARDENING,
            mounts=[
                {"service": "web", "target": "/a"},
                {"service": "php", "target": "/b"},
                {"service": "web", "target": "/c"},
            ],
        )
        self.assertEqual(
            MODULE.hardened_services({"php_hardening": entry}), ["php", "web"]
        )

    def test_a_role_without_php_hardening_has_none(self):
        self.assertEqual(MODULE.hardened_services({"data": {"type": "volume"}}), [])

    def test_the_fpm_drop_in_does_not_count(self):
        self.assertEqual(MODULE.hardened_services({"php_fpm_hardening": HARDENING}), [])


class TestLookup(TestCase):
    def _run(self, volumes_by_role, **kwargs):
        lookup = MODULE.LookupModule()
        lookup._loader = mock.MagicMock()
        lookup._templar = mock.MagicMock()
        volume = mock.MagicMock()
        volume.run.side_effect = lambda terms, **_kw: [volumes_by_role[terms[0]]]
        with mock.patch.object(MODULE, "lookup_loader") as loader:
            loader.get.return_value = volume
            return lookup.run([], variables={}, **kwargs)[0]

    def test_maps_hardened_roles_to_their_entity(self):
        result = self._run(
            {"web-app-nextcloud": {"php_hardening": HARDENING}, "svc-db-postgres": {}},
            group_names=["web-app-nextcloud", "svc-db-postgres"],
        )
        self.assertEqual(result, {"nextcloud": ["nextcloud"]})

    def test_no_deployed_php_role_yields_an_empty_map(self):
        self.assertEqual(
            self._run({"svc-db-postgres": {}}, group_names=["svc-db-postgres"]), {}
        )

    def test_missing_group_names_raises(self):
        with self.assertRaises(AnsibleError):
            self._run({})


if __name__ == "__main__":
    main()
