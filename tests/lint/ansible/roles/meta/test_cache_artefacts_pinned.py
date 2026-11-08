from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.cache.artefacts import HUB, artefacts, breaches, shape_breaches


def _offenders() -> list[str]:
    return [*shape_breaches(), *breaches(artefacts())]


class TestCacheArtefactsPinned(unittest.TestCase):
    def test_every_artefact_keeps_the_manifest_contract(self) -> None:
        offenders = _offenders()
        self.assertFalse(
            offenders,
            "artefacts breaking the manifest contract:\n"
            + "\n".join(f"  - {line}" for line in offenders),
        )

    def test_the_guard_reports_a_branch_pin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            meta = Path(tmp) / "roles" / "svc-model" / "meta"
            meta.mkdir(parents=True)
            (meta / "networks.yml").write_text(
                "cache:\n"
                "  artefacts:\n"
                "    model:\n"
                f"      url: https://{HUB}/o/r/resolve/main/m.gguf\n"
                '      revision: "main"\n'
                f'      sha256: "{"0" * 64}"\n'
                '      bytes: "1"\n',
                encoding="utf-8",
            )
            listed = Path(tmp) / "roles" / "svc-list" / "meta"
            listed.mkdir(parents=True)
            (listed / "networks.yml").write_text(
                "cache:\n  artefacts:\n    - model\n", encoding="utf-8"
            )
            with patch("utils.cache.hosts.ROLES_DIR", Path(tmp) / "roles"):
                offenders = _offenders()
        self.assertTrue(
            any("not a 40-digit lowercase hex commit" in line for line in offenders),
            f"the guard missed a resolve/main pin: {offenders}",
        )
        self.assertTrue(
            any("no cache: repository upstream" in line for line in offenders),
            f"the guard missed an unserved url: {offenders}",
        )
        self.assertIn(
            "svc-list: cache: artefacts: is a list, not a mapping",
            offenders,
            "the guard missed a section that is not a mapping",
        )


if __name__ == "__main__":
    unittest.main()
