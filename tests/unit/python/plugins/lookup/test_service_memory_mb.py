from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from ansible.errors import AnsibleError

from plugins.lookup.service_memory_mb import LookupModule, docker_bytes, share_mb

_APP = "web-app-demo"
_PROVIDER = "svc-db-cache"


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


class _LookupCase(unittest.TestCase):
    def _run(
        self,
        services: dict,
        variables: dict,
        terms: list,
        provided: dict | None = None,
        **kwargs,
    ) -> int:
        templar = MagicMock()
        templar.available_variables = variables
        templar.template.side_effect = lambda value: {"{{ HOST }}": "1.5g"}.get(
            value, value
        )
        applications = MagicMock()
        applications.run.return_value = [
            {
                _APP: {"services": services},
                _PROVIDER: {"services": provided or {}},
            }
        ]
        lookup = LookupModule(loader=None, templar=templar)
        with patch(
            "plugins.lookup.service_memory_mb.lookup_loader.get",
            return_value=applications,
        ):
            return lookup.run(terms, variables=variables, **kwargs)[0]


class TestLookupResolvesTheContainerLimit(_LookupCase):
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


class TestProviderCapsAnInheritedLimit(_LookupCase):
    def _sidecar(
        self,
        services: dict,
        provided: dict | None = None,
        share: float = 0.8,
        variables: dict | None = None,
        **kwargs,
    ) -> int:
        if provided is None:
            provided = {"cache": {"mem_limit": "512m"}}
        return self._run(
            services,
            variables or {},
            [_APP, "cache", share],
            provided=provided,
            **(kwargs or {"provider": _PROVIDER}),
        )

    def test_an_inherited_limit_is_capped_at_the_providers(self) -> None:
        for inherited, expected in (("4g", 409), ("1g", 409), ("512m", 409)):
            with self.subTest(inherited=inherited):
                self.assertEqual(
                    self._sidecar({"demo": {"mem_limit": inherited}}), expected
                )

    def test_a_small_inherited_limit_stays_below_its_own_container(self) -> None:
        self.assertEqual(self._sidecar({"demo": {"mem_limit": "256m"}}), 204)

    def test_the_cap_uses_the_share_of_the_call(self) -> None:
        self.assertEqual(self._sidecar({"demo": {"mem_limit": "4g"}}, share=0.25), 128)

    def test_the_host_default_is_capped_as_well(self) -> None:
        variables = {"RESOURCE_MEM_LIMIT": "{{ HOST }}"}

        self.assertEqual(self._sidecar({}, variables=variables), 409)

    def test_a_declared_limit_is_not_capped(self) -> None:
        services = {"cache": {"mem_limit": "1g"}, "demo": {"mem_limit": "4g"}}

        self.assertEqual(self._sidecar(services), 819)

    def test_a_provider_without_a_limit_raises_even_when_nothing_is_capped(
        self,
    ) -> None:
        for services in (
            {"demo": {"mem_limit": "4g"}},
            {"cache": {"mem_limit": "1g"}},
        ):
            with self.subTest(services=services), self.assertRaises(AnsibleError):
                self._sidecar(services, provided={"cache": {}})

    def test_only_the_providers_limit_for_that_very_service_counts(self) -> None:
        with self.assertRaises(AnsibleError):
            self._run(
                {"demo": {"mem_limit": "4g"}},
                {},
                [_APP, "store", 0.8],
                provided={"cache": {"mem_limit": "512m"}},
                provider=_PROVIDER,
            )

    def test_a_provider_that_is_no_role_raises(self) -> None:
        for provider in ("", None, "svc-db-missing"):
            with self.subTest(provider=provider), self.assertRaises(AnsibleError):
                self._sidecar({"cache": {"mem_limit": "1g"}}, provider=provider)

    def test_a_misspelled_option_raises(self) -> None:
        with self.assertRaises(AnsibleError):
            self._sidecar({"demo": {"mem_limit": "4g"}}, providr=_PROVIDER)


if __name__ == "__main__":
    unittest.main()
