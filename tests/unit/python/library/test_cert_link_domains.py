from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path
from typing import TYPE_CHECKING

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from types import ModuleType

sys.path.insert(0, str(PROJECT_ROOT))

from utils import cert_utils

MODULE_PATH = PROJECT_ROOT / "library" / "cert_link_domains.py"


def _load_cert_link_domains() -> ModuleType:
    sys.modules.setdefault("ansible.module_utils.cert_utils", cert_utils)
    spec = importlib.util.spec_from_file_location(
        "library_cert_link_domains", str(MODULE_PATH)
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load: {MODULE_PATH}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod


_MOD = _load_cert_link_domains()


class LinkDomainTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        (self.base / "certbundle-abc-00001").mkdir()
        (self.base / "certbundle-abc-00002").mkdir()
        self.link = self.base / "meet.example"

    def tearDown(self):
        self._tmp.cleanup()

    def _link(self, folder):
        with mock.patch.object(
            _MOD.CertUtils, "find_cert_for_domain", return_value=folder
        ):
            return _MOD.link_domain("meet.example", str(self.base))

    def test_links_domain_to_covering_bundle(self):
        self.assertEqual(self._link("certbundle-abc-00001"), "linked")
        self.assertEqual(str(self.link.readlink()), "certbundle-abc-00001")

    def test_repoints_link_to_newer_bundle(self):
        self.link.symlink_to("certbundle-abc-00001")
        self.assertEqual(self._link("certbundle-abc-00002"), "linked")
        self.assertEqual(str(self.link.readlink()), "certbundle-abc-00002")

    def test_keeps_link_already_on_covering_bundle(self):
        self.link.symlink_to("certbundle-abc-00001")
        self.assertEqual(self._link("certbundle-abc-00001"), "kept")

    def test_keeps_dedicated_lineage_directory(self):
        self.link.mkdir()
        self.assertEqual(self._link("certbundle-abc-00001"), "kept")
        self.assertFalse(self.link.is_symlink())

    def test_reports_domain_without_covering_cert(self):
        self.assertEqual(self._link(None), "missing")
        self.assertFalse(self.link.exists(follow_symlinks=False))


if __name__ == "__main__":
    unittest.main()
