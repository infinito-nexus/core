"""Which ganesha LOG components a debug run raises, and which it must not."""

from __future__ import annotations

import re
import unittest

from jinja2 import Environment, StrictUndefined, select_autoescape

from utils.cache.files import read_text

from . import PROJECT_ROOT

TEMPLATE = (
    PROJECT_ROOT / "roles" / "svc-storage-nfs-server" / "templates" / "ganesha.conf.j2"
)
DEBUG_RUN_LEVELS = {"INIT": "FULL_DEBUG", "DISPATCH": "DEBUG"}


def _render(*, mode_debug: bool) -> str:
    """Render ganesha.conf.

    Args:
        mode_debug: the MODE_DEBUG value of the deploy.
    """
    env = Environment(
        trim_blocks=True,
        lstrip_blocks=True,
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    env.filters["bool"] = bool

    def lookup(kind: str) -> str:
        if kind == "nfs_export_base":
            return "/srv/nfs"
        raise AssertionError(f"unexpected lookup: {kind}")

    return env.from_string(read_text(str(TEMPLATE))).render(
        lookup=lookup,
        MODE_DEBUG=mode_debug,
        SVC_STORAGE_NFS_SERVER_MINOR_VERSIONS="0, 1, 2",
        svc_storage_nfs_server_allowed_ips=["192.168.244.10"],
        STORAGE_NFS_STATE_PATH="/srv/nfs/infinito-state",
        SVC_STORAGE_NFS_SERVER_STATE_ALLOWED_CIDRS=["192.168.244.0/24"],
    )


def _component_levels(rendered: str) -> dict[str, str]:
    """Map every LOG component the config raises to its level.

    Args:
        rendered: the rendered ganesha.conf.
    """
    block = re.search(r"components\s*\{(?P<body>[^}]*)\}", rendered)
    if block is None:
        return {}
    return dict(re.findall(r"([A-Z0-9_]+)\s*=\s*([A-Z_]+)\s*;", block["body"]))


class TestGaneshaLogLevels(unittest.TestCase):
    def test_debug_runs_raise_exactly_the_startup_components(self):
        self.assertEqual(
            _component_levels(_render(mode_debug=True)),
            DEBUG_RUN_LEVELS,
            "a debug run raises INIT and DISPATCH only: nfs_Init_svc(), which binds "
            "2049, logs under DISPATCH, so a wedged startup stays describable; a "
            "per-request component such as NFS_V4 at DEBUG writes about a dozen "
            "lines per NFS compound and filled the swarm runner disk in CI run "
            "40625679270 (odoo#1, nfs-server +12.6 GB)",
        )

    def test_regular_runs_render_no_log_block(self):
        rendered = _render(mode_debug=False)
        self.assertIsNone(
            re.search(r"^\s*LOG\s*\{", rendered, re.MULTILINE),
            "outside MODE_DEBUG ganesha keeps the -N NIV_EVENT level of its "
            "command line for every component",
        )


if __name__ == "__main__":
    unittest.main()
