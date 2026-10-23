"""What a deploy pass carries from the host into the infinito container.

Ansible runs inside that container, so a variable the host exports reaches a
lookup only when ``_run_deploy`` forwards it explicitly. ``APP_ID`` is the
deploy workflow's name for the row's app, and
:mod:`plugins.lookup.guide_role` reads it to pin the documentation replay.

``guide_host`` names the app a documentation row rides along with, and
``web-app-docs``'s playwright environment reads it to decide whether this row
owns the language assertion. Unforwarded, the lookup is empty, the comparison
against the row's own id is true everywhere, and every passenger row pays the
two Sphinx builds the gate exists to skip.
"""

from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from cli.administration.deploy.development.deploy.run import _run_deploy


class _Compose:
    def __init__(self) -> None:
        self.extra_env: dict[str, str] = {}

    def exec(self, cmd, *, check, live, extra_env):
        self.extra_env = extra_env
        return SimpleNamespace(returncode=0)


def _deploy() -> dict[str, str]:
    compose = _Compose()
    _run_deploy(
        compose,
        deploy_ids=["web-app-docs"],
        debug=False,
        passthrough=[],
        inventory_dir="/srv/inv",
        container_name="infinito",
    )
    return compose.extra_env


class TestForwardedEnv(unittest.TestCase):
    @patch.dict(os.environ, {"APP_ID": "web-app-nextcloud"}, clear=True)
    def test_app_id_reaches_the_container(self):
        self.assertEqual(_deploy().get("APP_ID"), "web-app-nextcloud")

    @patch.dict(os.environ, {}, clear=True)
    def test_an_unset_app_id_is_not_invented(self):
        self.assertNotIn("APP_ID", _deploy())

    @patch.dict(os.environ, {"APP_ID": ""}, clear=True)
    def test_an_empty_app_id_is_not_forwarded(self):
        self.assertNotIn("APP_ID", _deploy())

    @patch.dict(os.environ, {"guide_host": "web-app-moodle"}, clear=True)
    def test_the_guide_host_reaches_the_container(self):
        self.assertEqual(_deploy().get("guide_host"), "web-app-moodle")

    @patch.dict(os.environ, {}, clear=True)
    def test_an_unset_guide_host_is_not_invented(self):
        self.assertNotIn("guide_host", _deploy())


if __name__ == "__main__":
    unittest.main()
