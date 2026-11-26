"""uwsgi's HTTP router writes 8 B per possible fd; uncapped under the mdad daemon (2147483584) it pinned 16 GiB in run 42239638356."""

from __future__ import annotations

import unittest

from jinja2 import Environment, StrictUndefined, select_autoescape

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml, load_yaml_str
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

_ROLE = PROJECT_ROOT / "roles/web-app-matrix"
_ADDON = _ROLE / "meta/addons/synapse-usage-exporter.yml"
_VARS_MAIN = _ROLE / ROLE_FILE_VARS_MAIN
_MDAD_VARS = _ROLE / "templates/flavor/ansible/vars.yml.j2"

_VAR = "MATRIX_ADDON_SYNAPSE_USAGE_EXPORTER_NOFILE"
_EXTRA_ARGUMENTS = "matrix_synapse_usage_exporter_container_extra_arguments"
_NOFILE_PATH = "addons.synapse-usage-exporter.config.nofile"
_UWSGI_GEVENT_CORES = 1000
_FD_SLOT_BYTES = 8
_TABLE_BUDGET_BYTES = 16 * 1024 * 1024


def _render(source: str, **variables) -> str:
    """
    Args:
        source: a Jinja string of the role.
        variables: the variables it renders with.

    Returns:
        The rendered string.
    """
    return (
        Environment(
            undefined=StrictUndefined,
            autoescape=select_autoescape(default_for_string=False),
        )
        .from_string(source)
        .render(**variables)
    )


def _cap() -> str:
    """
    Returns:
        The role's nofile cap rendered against the addon's own config.
    """
    answers = {("config", _NOFILE_PATH): load_yaml(_ADDON)["config"]["nofile"]}
    return _render(
        load_yaml(_VARS_MAIN)[_VAR],
        application_id="web-app-matrix",
        lookup=lambda kind, _app, path: answers[(kind, path)],
    )


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
        self.assertEqual(_cap(), str(load_yaml(_ADDON)["config"]["nofile"]))

    def test_mdad_creates_the_exporter_with_the_cap(self) -> None:
        lines = read_text(str(_MDAD_VARS)).splitlines()
        start = next(
            (i for i, line in enumerate(lines) if line == f"{_EXTRA_ARGUMENTS}:"),
            None,
        )
        self.assertIsNotNone(start, "mdad would create the exporter uncapped")
        end = next(
            i for i in range(start + 1, len(lines)) if not lines[i].startswith(" ")
        )
        cap = _cap()
        block = load_yaml_str(_render("\n".join(lines[start:end]), **{_VAR: cap}))
        self.assertEqual(block[_EXTRA_ARGUMENTS], [f"--ulimit=nofile={cap}:{cap}"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
