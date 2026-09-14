from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cli.administration.deploy.development.coredns import CoreDNSCorefileRenderer
from utils.cache.files import PROJECT_ROOT, read_text

TEMPLATE = "compose/coredns/Corefile.tmpl"


def _render() -> str:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / ".env").write_text(
            'INFINITO_DOMAIN=infinito.test\nINFINITO_IP4="172.30.0.10"\n',
            encoding="utf-8",
        )
        template = root / TEMPLATE
        template.parent.mkdir(parents=True)
        template.write_text(read_text(str(PROJECT_ROOT / TEMPLATE)), encoding="utf-8")
        out = CoreDNSCorefileRenderer(repo_root=root).render(show_preview=False)
        return read_text(str(out))


class TestCoreDNSCorefileRenderer(unittest.TestCase):
    def test_the_domain_regex_is_derived_from_the_domain_escaped_once(self) -> None:
        corefile = _render()
        self.assertIn("match ^infinito\\.test\\.$", corefile)
        self.assertIn("match ^(.*)\\.infinito\\.test\\.$", corefile)
        self.assertNotIn("\\\\", corefile)
        self.assertNotIn("${", corefile)

    def test_the_deployment_zone_answers_every_type_itself(self) -> None:
        corefile = _render()
        catch_all = "template IN ANY infinito.test {"
        self.assertIn(catch_all, corefile)
        self.assertIn("IN SOA ns.infinito.test. hostmaster.infinito.test.", corefile)
        lines = corefile.splitlines()
        self.assertLess(
            max(
                index
                for index, line in enumerate(lines)
                if line.strip() == "template IN A {"
            ),
            next(
                index for index, line in enumerate(lines) if line.strip() == catch_all
            ),
            "the zone-wide template must come after the A templates, or it "
            "answers their names with NODATA and the deployment loses its own "
            "addresses",
        )
        self.assertLess(
            lines.index(f"  {catch_all}"),
            next(index for index, line in enumerate(lines) if "forward ." in line),
            "a type the zone does not answer must not reach the public "
            "resolvers: they return NXDOMAIN for the reserved TLD, and a "
            "caching resolver in front then denies every type of that name, "
            "including the A record the deployment depends on",
        )


if __name__ == "__main__":
    unittest.main()
