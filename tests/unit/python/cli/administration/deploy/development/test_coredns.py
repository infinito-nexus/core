from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cli.administration.deploy.development.coredns import CoreDNSCorefileRenderer
from utils.cache.files import PROJECT_ROOT, read_text

TEMPLATE = "compose/coredns/Corefile.tmpl"


class TestCoreDNSCorefileRenderer(unittest.TestCase):
    def test_the_domain_regex_is_derived_from_the_domain_escaped_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text(
                'INFINITO_DOMAIN=infinito.test\nINFINITO_IP4="172.30.0.10"\n',
                encoding="utf-8",
            )
            template = root / TEMPLATE
            template.parent.mkdir(parents=True)
            template.write_text(
                read_text(str(PROJECT_ROOT / TEMPLATE)), encoding="utf-8"
            )
            out = CoreDNSCorefileRenderer(repo_root=root).render(show_preview=False)
            corefile = read_text(str(out))
        self.assertIn("match ^infinito\\.test\\.$", corefile)
        self.assertIn("match ^(.*)\\.infinito\\.test\\.$", corefile)
        self.assertNotIn("\\\\", corefile)
        self.assertNotIn("${", corefile)


if __name__ == "__main__":
    unittest.main()
