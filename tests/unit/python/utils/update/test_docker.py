from __future__ import annotations

import contextlib
import io
import os
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path

from utils.cache.files import read_text
from utils.roles.mapping import ROLE_FILE_META_SERVICES
from utils.update import docker
from utils.update.base import hold_reason
from utils.update.docker import (
    _registry_cursor,
    collect_entries,
    sourced_services,
    update_config_versions,
)

HELD = """odoo:
  image: odoo
  version: "19.0"
  hold:
    version: "19.0"
    reason: OCA publishes no 20.x of fs_storage
plain:
  image: example/plain
  version: "4.0"
"""

GROUP = """web:
  image: jitsi/web
  version: stable-9400
  hold:
    version: stable-9400
    reason: web 9700 drops the prosody handshake
prosody:
  image: jitsi/prosody
  version: stable-9400
plain:
  image: example/plain
  version: "4.0"
"""

REGISTRY = {
    "odoo": ["19.0", "20.0"],
    "example/plain": ["4.0", "5.0"],
    "jitsi/web": ["stable-9400", "stable-9700"],
    "jitsi/prosody": ["stable-9400", "stable-9700"],
}

SOURCED = """bundled:
  image: example/app
  version: v1.0.0
  update:
    type: http_regex
    url: https://example.invalid/bundle
    pattern: "app:(v[0-9.]+)"
tracked:
  image: example/side
  version: v2.0.0
  other_version: v3.0.0
  update:
    - key: other_version
      type: git_tags
      repository: https://example.invalid/side.git
plain:
  image: example/plain
  version: v4.0.0
"""


class TestRegistryCursor(unittest.TestCase):
    def test_v_prefixed_pin_seeds_cursor(self) -> None:
        self.assertEqual(_registry_cursor("v19.1.1"), "v")

    def test_bare_numeric_pin_scans_from_start(self) -> None:
        self.assertIsNone(_registry_cursor("19.1.1"))


class TestDeclaredSource(unittest.TestCase):
    def test_a_version_with_its_own_source_is_left_to_that_source(self) -> None:
        root = Path(tempfile.mkdtemp())
        config = root / "roles" / "web-app-example" / ROLE_FILE_META_SERVICES
        config.parent.mkdir(parents=True)
        config.write_text(SOURCED, encoding="utf-8")

        self.assertEqual(sourced_services(config), {"bundled"})
        self.assertEqual(
            sorted(entry.service for entry in collect_entries(root)),
            ["plain", "tracked"],
        )


def _role_root(services: str) -> Path:
    root = Path(tempfile.mkdtemp())
    config = root / "roles" / "web-app-example" / ROLE_FILE_META_SERVICES
    config.parent.mkdir(parents=True)
    config.write_text(services, encoding="utf-8")
    return root


class TestHold(unittest.TestCase):
    def _outdated(
        self, services: str, actions: str = "false"
    ) -> tuple[list[tuple[str, str]], str]:
        stdout = io.StringIO()
        with (
            mock.patch.dict(
                os.environ, {"INFINITO_WORKER_FETCH": "2", "GITHUB_ACTIONS": actions}
            ),
            mock.patch.object(
                docker, "fetch_dockerhub_tags", lambda image: REGISTRY.get(image, [])
            ),
            contextlib.redirect_stdout(stdout),
        ):
            updates = docker.find_outdated_updates(_role_root(services))
        return [(u.entry.service, u.latest) for u in updates], stdout.getvalue()

    def test_a_held_pin_is_not_proposed_but_reported(self) -> None:
        proposed, output = self._outdated(HELD)

        self.assertNotIn("odoo", {service for service, _latest in proposed})
        self.assertIn("Held Docker image", output)
        self.assertIn(
            "[hold] web-app-example/odoo: odoo stays at 19.0, 20.0 is available; "
            "held by odoo: OCA publishes no 20.x of fs_storage",
            output,
        )

    def test_a_held_pin_is_a_warning_annotation_in_ci(self) -> None:
        _proposed, output = self._outdated(HELD, actions="true")

        self.assertIn(
            "::warning title=Held Docker image,"
            f"file=roles/web-app-example/{ROLE_FILE_META_SERVICES}::[hold] "
            "web-app-example/odoo:",
            output,
        )

    def test_a_held_member_holds_its_whole_release_group(self) -> None:
        proposed, output = self._outdated(GROUP)

        self.assertEqual(proposed, [("plain", "5.0")])
        for service in ("web", "prosody"):
            with self.subTest(service=service):
                self.assertIn(
                    f"[hold] web-app-example/{service}: jitsi/{service} stays at "
                    "stable-9400, stable-9700 is available; held by web: "
                    "web 9700 drops the prosody handshake",
                    output,
                )

    def test_an_unheld_release_group_still_moves_together(self) -> None:
        unheld = GROUP.replace(
            "  hold:\n    version: stable-9400\n"
            "    reason: web 9700 drops the prosody handshake\n",
            "",
        )

        proposed, _output = self._outdated(unheld)

        self.assertEqual(
            sorted(proposed),
            [("plain", "5.0"), ("prosody", "stable-9700"), ("web", "stable-9700")],
        )

    def test_an_unheld_pin_is_still_proposed(self) -> None:
        proposed, _stderr = self._outdated(HELD)

        self.assertEqual(proposed, [("plain", "5.0")])

    def test_without_the_hold_the_pin_is_proposed(self) -> None:
        unheld = HELD.replace(
            '  hold:\n    version: "19.0"\n'
            "    reason: OCA publishes no 20.x of fs_storage\n",
            "",
        )

        proposed, _stderr = self._outdated(unheld)

        self.assertIn(("odoo", "20.0"), proposed)

    def test_a_hold_without_reason_is_rejected(self) -> None:
        for hold in (
            {"version": "19.0"},
            {"version": "19.0", "reason": "  "},
            None,
            "19.0",
        ):
            with self.subTest(hold=hold), self.assertRaises(ValueError):
                hold_reason({"version": "19.0", "hold": hold}, "19.0")

    def test_a_hold_of_another_version_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "20.0"):
            hold_reason({"hold": {"version": "20.0", "reason": "x"}}, "19.0")

    def test_the_updater_refuses_a_hold_without_reason(self) -> None:
        root = _role_root(
            HELD.replace("    reason: OCA publishes no 20.x of fs_storage\n", "")
        )

        with self.assertRaisesRegex(ValueError, "odoo: hold of '19.0' states no"):
            collect_entries(root)

    def test_an_entity_without_hold_has_no_reason(self) -> None:
        self.assertEqual(hold_reason({"version": "19.0"}, "19.0"), "")


class TestUpdateDocker(unittest.TestCase):
    def test_update_config_versions_updates_only_target_services(self) -> None:
        original = """moodle:
  version:            "4.5" # Keep comment
  image:              bitnamilegacy/moodle
nginx:
  version:            alpine
  image:              nginx
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "main.yml"
            config_path.write_text(original, encoding="utf-8")

            changed = update_config_versions(config_path, {"moodle": "5.0"})

            self.assertTrue(changed)
            updated = read_text(str(config_path))
            self.assertIn('version:            "5.0" # Keep comment', updated)
            self.assertIn("version:            alpine", updated)
            self.assertNotIn('version:            "4.5" # Keep comment', updated)

    def test_a_bump_drops_the_image_tag_suppression_of_the_old_tag(self) -> None:
        original = """penpot:
  image: penpotapp/exporter
  version: "2.18.5"
  security:
    suppressions:
      # nocheck: cve upstream ships no rebuild yet
      - image_tag: "2.18.5"
        until: 2026-12-31
# nocheck: shared
nginx:
  image: nginx
  version: "1.29"
  security:
    suppressions:
      # nocheck: cve upstream ships no rebuild yet
      - image_tag: "1.29"
        until: 2026-12-31
"""
        expected = original.replace(
            """  version: "2.18.5"
  security:
    suppressions:
      # nocheck: cve upstream ships no rebuild yet
      - image_tag: "2.18.5"
        until: 2026-12-31
""",
            '  version: "2.18.6"\n',
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "main.yml"
            config_path.write_text(original, encoding="utf-8")

            update_config_versions(config_path, {"penpot": "2.18.6"})

            self.assertEqual(read_text(str(config_path)), expected)


if __name__ == "__main__":
    unittest.main()
