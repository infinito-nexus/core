from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from ansible.errors import AnsibleError

from plugins.lookup.service_memory_mb import LookupModule, docker_bytes, share_mb

_APP = "web-app-demo"


class TestDockerBytes(unittest.TestCase):
    def test_suffixes_are_binary(self) -> None:
        self.assertEqual(docker_bytes("512m"), 512 * 1024**2)
        self.assertEqual(docker_bytes("2g"), 2 * 1024**3)
        self.assertEqual(docker_bytes("1.5g"), 1536 * 1024**2)
        self.assertEqual(docker_bytes("64K"), 64 * 1024)
        self.assertEqual(docker_bytes("1gb"), 1024**3)

    def test_a_bare_number_is_bytes(self) -> None:
        self.assertEqual(docker_bytes(1048576), 1024**2)
        self.assertEqual(docker_bytes("2048"), 2048)

    def test_an_unreadable_size_raises(self) -> None:
        for size in ("", "lots", "2x", "-1g", None):
            with self.subTest(size=size), self.assertRaises(AnsibleError):
                docker_bytes(size)


class TestShareMb(unittest.TestCase):
    def test_share_of_the_limit_in_whole_mebibytes(self) -> None:
        cases = (
            ("2g", 0.5, 1024),
            ("4g", 0.5, 2048),
            ("8g", 0.7, 5734),
            ("8g", 0.35, 2867),
            ("6g", 0.7, 4300),
            ("512m", 0.8, 409),
            ("256m", 0.75, 192),
            ("1.5g", 0.5, 768),
            ("1g", 1, 1024),
        )
        for mem_limit, share, expected in cases:
            with self.subTest(mem_limit=mem_limit, share=share):
                self.assertEqual(share_mb(mem_limit, share), expected)

    def test_a_share_outside_the_limit_raises(self) -> None:
        for share in (0, -0.5, 1.01, "half", None):
            with self.subTest(share=share), self.assertRaises(AnsibleError):
                share_mb("2g", share)

    def test_a_result_below_one_mebibyte_raises(self) -> None:
        with self.assertRaises(AnsibleError):
            share_mb("1m", 0.5)


class TestLookupResolvesTheContainerLimit(unittest.TestCase):
    def _run(self, services: dict, variables: dict, terms: list) -> int:
        templar = MagicMock()
        templar.available_variables = variables
        templar.template.side_effect = lambda value: {"{{ HOST }}": "1.5g"}.get(
            value, value
        )
        applications = MagicMock()
        applications.run.return_value = [{_APP: {"services": services}}]
        lookup = LookupModule(loader=None, templar=templar)
        with patch(
            "plugins.lookup.service_memory_mb.lookup_loader.get",
            return_value=applications,
        ):
            return lookup.run(terms, variables=variables)[0]

    def test_the_named_service_wins(self) -> None:
        services = {"search": {"mem_limit": "2g"}, "demo": {"mem_limit": "8g"}}

        self.assertEqual(self._run(services, {}, [_APP, "search", 0.5]), 1024)

    def test_the_primary_entity_backs_an_undeclared_service(self) -> None:
        services = {"search": {}, "demo": {"mem_limit": "8g"}}

        self.assertEqual(self._run(services, {}, [_APP, "search", 0.5]), 4096)

    def test_the_host_default_backs_an_undeclared_role(self) -> None:
        variables = {"RESOURCE_MEM_LIMIT": "{{ HOST }}"}

        self.assertEqual(
            self._run({"search": {}}, variables, [_APP, "search", 0.5]), 768
        )

    def test_no_limit_anywhere_raises(self) -> None:
        with self.assertRaises(AnsibleError):
            self._run({"search": {}}, {}, [_APP, "search", 0.5])

    def test_the_term_count_is_checked(self) -> None:
        with self.assertRaises(AnsibleError):
            self._run({"search": {"mem_limit": "2g"}}, {}, [_APP, "search"])


if __name__ == "__main__":
    unittest.main()
