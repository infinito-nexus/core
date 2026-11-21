from __future__ import annotations

import unittest

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

ROLE = PROJECT_ROOT / "roles/web-app-peertube"
ADDON = ROLE / "meta/addons/peertube-plugin-auth-openid-connect.yml"
VARS = ROLE / ROLE_FILE_VARS_MAIN
SETTINGS = ROLE / "vars/oidc-settings.yml"
ENABLE = ROLE / "tasks/oidc/enable.yml"


def enable_tasks() -> list[dict]:
    return load_yaml_str(read_text(str(ENABLE)))


def task_named(prefix: str) -> dict:
    return next(task for task in enable_tasks() if task["name"].startswith(prefix))


class TestPeertubeOidcAccountLinking(unittest.TestCase):
    def test_accounts_are_keyed_by_the_sub_claim(self) -> None:
        self.assertEqual(
            load_yaml_str(read_text(str(SETTINGS)))["oidc_settings"][
                "external-id-property"
            ],
            "sub",
            "peertube-plugin-auth-openid-connect 2.1.1 dist/main.js:101-114,575-589 "
            "offers 'email', 'username' and 'none' beside 'sub'; anything but 'sub' "
            "keys the PeerTube account on a value the user or the provider can change",
        )

    def test_the_plugin_version_is_pinned_and_watched(self) -> None:
        addon = load_yaml_str(read_text(str(ADDON)))
        self.assertEqual(addon["version"], "2.1.1")
        self.assertEqual(
            addon["update"],
            {"type": "npm", "package": "peertube-plugin-auth-openid-connect"},
        )
        self.assertEqual(
            load_yaml_str(read_text(str(VARS)))["PEERTUBE_OIDC_PLUGIN_VERSION"],
            "{{ lookup('config', application_id, 'addons.' ~ PEERTUBE_OIDC_PLUGIN ~ "
            "'.version') }}",
        )

    def test_the_pinned_version_is_what_gets_installed(self) -> None:
        reason = (
            "an install without --plugin-version takes whatever npm publishes last, and "
            "a presence-only check keeps an old unpinned install forever, so the pin "
            "would never reach a running PeerTube"
        )
        check = task_named("🔎 Read the installed OIDC plugin version")
        self.assertIn("package.json').version", check["shell"], reason)
        block = task_named("📦 Install auth-openid-connect plugin")
        self.assertIn(
            "(peertube_oidc_plugin_check.stdout | trim) != PEERTUBE_OIDC_PLUGIN_VERSION",
            block["when"],
            reason,
        )
        install = next(
            task
            for task in block["block"]
            if "plugin:install" in str(task.get("ansible.builtin.shell"))
        )
        self.assertIn(
            "--plugin-version {{ PEERTUBE_OIDC_PLUGIN_VERSION | quote }}",
            install["ansible.builtin.shell"],
            reason,
        )


if __name__ == "__main__":
    unittest.main()
