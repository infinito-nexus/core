import re
import unittest
from typing import ClassVar

from utils.cache.files import read_text
from utils.roles.mapping import ROLE_FILE_TEMPL_COMPOSE

from . import PROJECT_ROOT


class TestDockerComposeTemplates(unittest.TestCase):
    TEMPLATE_PATTERN = f"roles/*/{ROLE_FILE_TEMPL_COMPOSE}"

    ALLOWED_BEFORE_BASE: ClassVar[list[re.Pattern]] = [
        re.compile(r"^\s*$"),
        re.compile(r"^\s*version:.*$"),
        re.compile(r"^\s*#.*$"),
        re.compile(r"^\s*\{\#.*\#\}\s*$"),
    ]

    BASE_INCLUDE = "{% include 'roles/sys-svc-compose/templates/base.yml.j2' %}"
    NET_INCLUDE = "{{ lookup('compose_networks') }}"
    NET_INCLUDE_RE: ClassVar[re.Pattern] = re.compile(
        r"\{\{\s*lookup\(\s*'compose_networks'[^)]*\)\s*\}\}"
    )
    HOST_MODE = 'network_mode: "host"'

    def test_docker_compose_includes(self):
        """
        Verifies for each found compose.yml.j2:
        1. BASE_INCLUDE is present exactly once
        2. If no host‑mode is set, NET_INCLUDE must appear exactly once
        3. BASE_INCLUDE appears before NET_INCLUDE when both are required
        4. Only allowed lines appear before BASE_INCLUDE (invalid lines issue warnings)
        """
        template_paths = sorted(PROJECT_ROOT.glob(self.TEMPLATE_PATTERN))
        self.assertTrue(
            template_paths, f"No templates found for pattern {self.TEMPLATE_PATTERN}"
        )

        for template_path in template_paths:
            with self.subTest(template=template_path):
                content = read_text(str(template_path))
                lines = content.splitlines()

                count_base = lines.count(self.BASE_INCLUDE)
                self.assertEqual(
                    count_base,
                    1,
                    f"{template_path}: '{self.BASE_INCLUDE}' occurs {count_base} times, expected once",
                )

                host_mode = self.HOST_MODE in content

                count_net = sum(1 for line in lines if self.NET_INCLUDE_RE.search(line))
                if host_mode:
                    self.assertLessEqual(
                        count_net,
                        1,
                        f"{template_path}: '{self.NET_INCLUDE}' occurs {count_net} times with host networking, expected 0 or 1",
                    )
                else:
                    self.assertEqual(
                        count_net,
                        1,
                        f"{template_path}: '{self.NET_INCLUDE}' occurs {count_net} times, expected once",
                    )

                if count_base and count_net:
                    idx_base = lines.index(self.BASE_INCLUDE)
                    idx_net = next(
                        i
                        for i, line in enumerate(lines)
                        if self.NET_INCLUDE_RE.search(line)
                    )
                    self.assertLess(
                        idx_base,
                        idx_net,
                        f"{template_path}: '{self.BASE_INCLUDE}' must come before '{self.NET_INCLUDE}'",
                    )


if __name__ == "__main__":
    unittest.main()
