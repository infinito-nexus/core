"""Unit tests for ``utils.roles.header_trust.header_trust_roles``."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from utils.roles.header_trust import header_trust_roles

RELAY = "proxy_set_header Remote-User $http_x_forwarded_user;\n"


def _role(roles_dir: Path, name: str, content: str) -> None:
    templates = roles_dir / name / "templates"
    templates.mkdir(parents=True)
    (templates / "proxy.conf.j2").write_text(content, encoding="utf-8")


class TestHeaderTrustRoles(unittest.TestCase):
    def test_a_role_naming_a_trusted_header_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            roles_dir = Path(tmp)
            _role(roles_dir, "web-app-trusting", RELAY)

            self.assertEqual(
                header_trust_roles(roles_dir),
                {"web-app-trusting": ["templates/proxy.conf.j2"]},
            )

    def test_a_head_nocheck_marker_exempts_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            roles_dir = Path(tmp)
            _role(roles_dir, "web-app-trusting", RELAY)
            _role(
                roles_dir,
                "web-app-exempt",
                "# nocheck: header-trust  reads no identity header\n" + RELAY,
            )

            self.assertEqual(
                sorted(header_trust_roles(roles_dir)), ["web-app-trusting"]
            )

    def test_a_blanking_line_is_no_trust(self):
        with tempfile.TemporaryDirectory() as tmp:
            roles_dir = Path(tmp)
            _role(roles_dir, "web-app-stripping", 'proxy_set_header Remote-User "";\n')

            self.assertEqual(header_trust_roles(roles_dir), {})


if __name__ == "__main__":
    unittest.main()
