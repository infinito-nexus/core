import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path

from plugins.lookup import i18n_catalogue


class TestI18nCatalogue(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.source = self.root / "team.yml"
        self.source.write_text("title: The team\n", encoding="utf-8")

    def _where(self, **kwargs) -> tuple:
        with mock.patch.object(i18n_catalogue, "keyed_catalogue") as keyed:
            i18n_catalogue.LookupModule().run(
                ["team", str(self.source)],
                variables={"playbook_dir": str(self.root)},
                **kwargs,
            )
        root, context, source, catalogs, domain = keyed.call_args.args
        self.assertEqual(
            (root, context("title"), source),
            (self.root, "team:title", {"title": "The team"}),
        )
        return catalogs, domain

    def test_catalogs_read_the_role_domain_named_by_the_prefix(self) -> None:
        self.assertEqual(self._where(catalogs="/roles/x"), (Path("/roles/x"), "team"))

    def test_without_catalogs_the_core_domain_answers(self) -> None:
        self.assertEqual(self._where(), (self.root, "core"))


if __name__ == "__main__":
    unittest.main()
