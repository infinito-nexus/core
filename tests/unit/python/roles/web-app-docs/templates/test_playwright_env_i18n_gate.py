from __future__ import annotations

import unittest
import unittest.mock as mock

from ansible.parsing.dataloader import DataLoader
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase
from ansible.template import Templar, trust_as_template

from utils.cache import PROJECT_ROOT
from utils.cache.files import read_text

APP = "web-app-docs"
TEMPLATE = PROJECT_ROOT / "roles" / APP / "templates" / "playwright.env.j2"
KEY = "DOCS_I18N_ASSERT_LANGUAGES"


class _Env(LookupBase):
    def __init__(self, environ: dict[str, str]):
        super().__init__()
        self._environ = environ

    def run(self, terms, variables=None, **kwargs):
        return [self._environ.get(name, "") for name in terms]


def assert_languages(**environ: str) -> str:
    """
    Args:
        environ: the controller environment the ``env`` lookup reads.

    Returns:
        The rendered value of ``DOCS_I18N_ASSERT_LANGUAGES``.
    """
    lines = read_text(str(TEMPLATE)).splitlines()
    start = next(
        i for i, row in enumerate(lines) if row.startswith("{% set docs_subject")
    )
    end = next(i for i, row in enumerate(lines) if row.startswith(f"{KEY}="))
    source = "\n".join(lines[start : end + 1])
    real_get = lookup_loader.get

    def get(name, *args, **kwargs):
        if name == "env":
            return _Env(environ)
        return real_get(name, *args, **kwargs)

    templar = Templar(loader=DataLoader(), variables={"application_id": APP})
    with mock.patch.object(lookup_loader, "get", side_effect=get):
        rendered = templar.template(trust_as_template(source))
    return next(
        row.removeprefix(f"{KEY}=")
        for row in rendered.splitlines()
        if row.startswith(f"{KEY}=")
    )


class TestI18nAssertGate(unittest.TestCase):
    def test_a_plain_docs_deploy_asserts_the_languages(self) -> None:
        self.assertEqual(assert_languages(), "true")

    def test_the_docs_row_of_a_matrix_asserts_the_languages(self) -> None:
        self.assertEqual(assert_languages(APP_ID=APP), "true")

    def test_a_passenger_row_skips_the_languages(self) -> None:
        self.assertEqual(assert_languages(APP_ID="web-app-moodle"), "false")

    def test_a_bundle_deploy_skips_the_languages(self) -> None:
        self.assertEqual(assert_languages(bundles="agents"), "false")

    def test_a_blank_bundle_list_still_asserts_the_languages(self) -> None:
        self.assertEqual(assert_languages(bundles="  "), "true")


if __name__ == "__main__":
    unittest.main()
