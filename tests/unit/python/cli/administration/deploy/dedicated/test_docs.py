from __future__ import annotations

import unittest

from utils.cache import PROJECT_ROOT
from utils.cache.files import read_text

DEPLOY_DOCS = PROJECT_ROOT / "cli/administration/deploy/README.md"
INVENTORY_DOCS = PROJECT_ROOT / "cli/administration/inventory/README.md"
DEPLOY_TERMS = (
    "## OpenBao references",
    "{openbao: <mount>/<path>#<field>}",
    "**Login order.**",
    "SEMAPHORE_JWT",
    "BAO_ROLE",
    "BAO_TOKEN",
    "BAO_ADDR",
    "BAO_CACERT",
    "**Pre-flight.**",
    "404",
    "403",
    "never the value",
    "**Create-only.**",
    "`cas` 0",
    "--password-file",
)
INVENTORY_TERMS = (
    "## OpenBao references",
    "--openbao <mount>/<prefix>",
    "#value}",
    "**Create-only rule.**",
    "`cas` 0",
    "**Login order.**",
    "**Pre-flight.**",
)


class TestTheDocs(unittest.TestCase):
    def test_the_docs_name_the_openbao_reference(self) -> None:
        for path, terms in (
            (DEPLOY_DOCS, DEPLOY_TERMS),
            (INVENTORY_DOCS, INVENTORY_TERMS),
        ):
            text = read_text(str(path))
            with self.subTest(path=path.name):
                self.assertEqual([term for term in terms if term not in text], [])
                self.assertNotIn("—", text)


if __name__ == "__main__":
    unittest.main()
