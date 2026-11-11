"""Every model reference names exactly one version."""

from __future__ import annotations

import unittest

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT, load

pins = load("pins")

SERVICES = PROJECT_ROOT / "roles" / "web-svc-assistant" / ROLE_FILE_META_SERVICES


class TestPinned(unittest.TestCase):
    def test_a_tagged_reference_is_pinned(self) -> None:
        self.assertTrue(pins.pinned("infinito/assistant-end-user:1.2.0"))

    def test_a_digest_reference_is_pinned(self) -> None:
        self.assertTrue(pins.pinned("infinito/assistant-embedding@sha256:" + "a" * 64))

    def test_a_bare_name_is_not_pinned(self) -> None:
        self.assertFalse(pins.pinned("infinito/assistant-end-user"))

    def test_a_floating_tag_is_not_pinned(self) -> None:
        for reference in ("assistant:latest", "assistant:LATEST", "assistant:main"):
            with self.subTest(reference=reference):
                self.assertFalse(pins.pinned(reference))

    def test_an_empty_reference_is_not_pinned(self) -> None:
        self.assertFalse(pins.pinned(""))

    def test_unpinned_names_the_offending_keys(self) -> None:
        models = {"end_user": "a:1.0.0", "consultant": "b", "embedding": "c:latest"}
        self.assertEqual(pins.unpinned(models), ["consultant", "embedding"])


class TestRoleConfigPinsEveryModel(unittest.TestCase):
    """Every model reference the role config names carries an explicit version."""

    def test_every_named_model_is_pinned(self) -> None:
        models = load_yaml_any(str(SERVICES))["assistant"]["models"]
        named = {key: value for key, value in models.items() if str(value).strip()}
        self.assertEqual(pins.unpinned(named), [])

    def test_the_config_names_one_model_per_role(self) -> None:
        models = load_yaml_any(str(SERVICES))["assistant"]["models"]
        self.assertEqual(sorted(models), ["consultant", "embedding", "end_user"])


if __name__ == "__main__":
    unittest.main()
