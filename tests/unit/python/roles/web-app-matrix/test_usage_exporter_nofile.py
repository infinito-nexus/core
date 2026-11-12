"""uwsgi's HTTP router writes 8 B per possible fd; uncapped under the mdad daemon (2147483584) it pinned 16 GiB in run 42239638356."""

from __future__ import annotations

import unittest

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

_ROLE = PROJECT_ROOT / "roles/web-app-matrix"
_ADDON = _ROLE / "meta/addons/synapse-usage-exporter.yml"
_VARS_MAIN = _ROLE / ROLE_FILE_VARS_MAIN
_MDAD_VARS = _ROLE / "templates/flavor/ansible/vars.yml.j2"

_VAR = "MATRIX_ADDON_SYNAPSE_USAGE_EXPORTER_NOFILE"
_UWSGI_GEVENT_CORES = 1000
_FD_SLOT_BYTES = 8
_TABLE_BUDGET_BYTES = 16 * 1024 * 1024


class TestUsageExporterNofile(unittest.TestCase):
    def test_the_cap_fits_the_gevent_cores_and_a_small_table(self) -> None:
        nofile = load_yaml(_ADDON)["config"]["nofile"]
        self.assertIsInstance(nofile, int)
        self.assertGreaterEqual(
            nofile,
            _UWSGI_GEVENT_CORES,
            "below uwsgi's gevent = 1000 the exporter silently drops async cores",
        )
        self.assertLessEqual(
            nofile * _FD_SLOT_BYTES,
            _TABLE_BUDGET_BYTES,
            "the cap no longer bounds uwsgi's per-fd router table",
        )

    def test_the_role_reads_the_cap_from_the_addon_config(self) -> None:
        self.assertIn(
            f"{_VAR}: \"{{{{ lookup('config', application_id, "
            "'addons.synapse-usage-exporter.config.nofile') }}\"",
            read_text(str(_VARS_MAIN)),
        )

    def test_mdad_creates_the_exporter_with_the_cap(self) -> None:
        lines = read_text(str(_MDAD_VARS)).splitlines()
        key = "matrix_synapse_usage_exporter_container_extra_arguments:"
        self.assertTrue(key in lines, "mdad would create the exporter uncapped")
        cap = f"{{{{ {_VAR} }}}}"
        self.assertEqual(
            lines[lines.index(key) + 1].strip(),
            f'- "--ulimit=nofile={cap}:{cap}"',
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
