from __future__ import annotations

import os
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path

from utils.cache.yaml import load_yaml_any
from utils.licensing.roles import declared

with mock.patch.dict(os.environ, {"INFINITO_WORKER_FETCH": "1"}):
    from tests.external.repository import test_urls_reachable as urls

ROLE = urls._REPO_ROOT / "roles" / "dsk-virtualbox"
INFO = ROLE / "meta" / "info.yml"
HOMEPAGE = load_yaml_any(str(INFO))["homepage"]
LICENCE = declared(ROLE).url
MUTED = "https://muted.infinito.nexus/page"  # nocheck: url
KEPT = "https://kept.infinito.nexus/page"  # nocheck: url


def _collect(*paths: Path) -> dict[str, list]:
    with mock.patch.object(urls, "_repo_files", return_value=list(paths)):
        return urls._collect_occurrences(urls._REPO_ROOT)


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


class TestSourceMarkerCoversCatalogs(unittest.TestCase):
    def test_virtualbox_catalog_entry_inherits_the_role_markers(self) -> None:
        self.assertTrue(all(map(urls._is_live_literal_url, (HOMEPAGE, LICENCE))))
        with tempfile.TemporaryDirectory() as scratch:
            catalog = _write(
                Path(scratch) / "docs.po",
                f'msgid "[a]({LICENCE}) and [b]({KEPT})"\nmsgstr ""\n',
            )

            collected = _collect(INFO, ROLE / "meta" / "license.yml", catalog)

        self.assertIsNone(collected.get(HOMEPAGE))
        self.assertIsNone(collected.get(LICENCE))
        self.assertEqual([occ.file for occ in collected[KEPT]], [catalog])

    def test_an_unmarked_source_line_keeps_its_url_probed(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            marked = _write(root / "meta.yml", f"url: {MUTED} # nocheck: url\n")
            readme = _write(root / "README.md", f"See {MUTED}.\n")
            catalog = _write(
                root / "docs.po", f'# nocheck: url\nmsgid "{KEPT}"\nmsgstr ""\n'
            )
            notes = _write(root / "NOTES.md", f"See {KEPT}.\n")

            collected = _collect(marked, readme, catalog, notes)

        self.assertEqual([occ.file for occ in collected[MUTED]], [readme])
        self.assertEqual([occ.file for occ in collected[KEPT]], [notes])


if __name__ == "__main__":
    unittest.main()
