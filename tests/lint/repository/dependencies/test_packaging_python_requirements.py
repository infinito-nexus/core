#!/usr/bin/env python3

from __future__ import annotations

import re
import unittest

from utils.cache.files import read_text

from . import PROJECT_ROOT


class TestPackagingPythonRequirements(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo_root = PROJECT_ROOT
        cls.arch_pkgbuild = cls.repo_root / "packaging" / "arch" / "PKGBUILD"
        cls.fedora_spec = cls.repo_root / "packaging" / "fedora" / "infinito-nexus.spec"
        cls.debian_control = cls.repo_root / "packaging" / "debian" / "control"

    def test_fedora_spec_relaxes_python_capability_on_el9_only(self):
        spec_text = read_text(str(self.fedora_spec))
        self.assertRegex(
            spec_text,
            re.compile(
                r"%if 0%\{\?rhel\} == 9\s+"
                r"Requires:\s+python3\s+"
                r"%else\s+"
                r"Requires:\s+python3 >= 3\.11\s+"
                r"%endif",
                re.MULTILINE,
            ),
        )

    def test_debian_control_keeps_explicit_python_311_floor(self):
        control_text = read_text(str(self.debian_control))
        self.assertIn(" python3 (>= 3.11),", control_text)

    def test_arch_pkgbuild_requires_docker_compose(self):
        pkgbuild_text = read_text(str(self.arch_pkgbuild))
        self.assertIn("  'docker-compose'", pkgbuild_text)

    def test_debian_control_requires_compose_v2_plugin(self):
        control_text = read_text(str(self.debian_control))
        self.assertIn(
            " docker-compose-v2 | docker-compose-plugin,",
            control_text,
        )
        self.assertNotIn(
            " docker-compose-v2 | docker-compose-plugin | docker-compose,",
            control_text,
        )

    def test_fedora_spec_requires_compose_plugin(self):
        spec_text = read_text(str(self.fedora_spec))
        self.assertIn("Requires:       docker-compose-plugin", spec_text)


if __name__ == "__main__":
    unittest.main()
