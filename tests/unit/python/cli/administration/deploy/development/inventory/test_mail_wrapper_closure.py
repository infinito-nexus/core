from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from cli.administration.inventory.validate.mail import validate_mail_wrapper
from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import dump_yaml_str, load_yaml_any
from utils.mail.provider import MAIL_WRAPPER, provider_roles
from utils.roles.applications.variants import (
    _resolve_round_include,
    services_overrides_for_round,
)
from utils.roles.mapping import ROLE_FILE_META_VARIANTS

ROLES_DIR = Path(PROJECT_ROOT) / "roles"
STALWART = "web-app-stalwart"
CONSUMER = "web-app-gitea"


def _include(primary: str, overrides: dict[str, dict]) -> tuple[str, ...]:
    return _resolve_round_include(primary_apps=[primary], services_overrides=overrides)


class TestMailWrapperClosure(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        shutil.rmtree(self.root)

    def _validate(self, include: tuple[str, ...]) -> list[str]:
        children = {role: {"hosts": {"host01": None}} for role in include}
        (self.root / "devices.yml").write_text(
            dump_yaml_str({"all": {"children": children}}), encoding="utf-8"
        )
        return validate_mail_wrapper(self.root, provider_roles(ROLES_DIR))

    def test_a_standalone_provider_pulls_the_wrapper_in(self) -> None:
        include = _include(STALWART, {})
        self.assertIn(MAIL_WRAPPER, include)
        self.assertEqual([], self._validate(include))

    def test_a_consumer_pulls_the_wrapper_and_its_provider_in(self) -> None:
        include = _include(CONSUMER, {})
        self.assertIn(MAIL_WRAPPER, include)
        self.assertIn(STALWART, include)
        self.assertEqual([], self._validate(include))

    def test_every_provider_variant_keeps_the_wrapper(self) -> None:
        variants = load_yaml_any(
            str(ROLES_DIR / STALWART / ROLE_FILE_META_VARIANTS), default_if_missing=[]
        )
        for index in range(len(variants)):
            with self.subTest(variant=index):
                overrides = services_overrides_for_round(
                    roles_dir=str(ROLES_DIR),
                    round_index=index,
                    primary_app_variants={STALWART: index},
                )
                include = _include(STALWART, overrides)
                self.assertIn(MAIL_WRAPPER, include)
                self.assertEqual([], self._validate(include))

    def test_a_provider_without_the_wrapper_is_caught(self) -> None:
        include = tuple(r for r in _include(STALWART, {}) if r != MAIL_WRAPPER)
        self.assertEqual(1, len(self._validate(include)))


if __name__ == "__main__":
    unittest.main()
