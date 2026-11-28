import unittest
from pathlib import Path
from typing import Any, ClassVar

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from plugins.filter.canonical_domains_map import (
    FilterModule as CanonicalDomainsFilter,
)
from plugins.filter.generate.all_domains import FilterModule as AllDomainsFilter
from utils.cache.applications import get_merged_applications
from utils.cache.domains import get_merged_domains
from utils.cache.files import PROJECT_ROOT
from utils.mail.provider import MAIL_WRAPPER
from utils.roles.entity.name import entity_name
from utils.roles.mapping import ROLE_FILE_META_DOMAINS
from utils.tests.caches import reset_caches

_GENERAL_VARS = Path(PROJECT_ROOT) / "group_vars" / "all" / "00_general.yml"
_ROLES_DIR = Path(PROJECT_ROOT) / "roles"
_STALWART = "web-app-stalwart"
_MAILU = "web-app-mailu"
_DOMAIN = "example.org"


def _trusted(path: Path) -> Any:
    return DataLoader().load_from_file(str(path), trusted_as_template=True)


def _scope(group_vars: dict[str, Any], roles: list[str], **extra: Any) -> dict:
    return {
        **group_vars,
        "DOMAIN_PRIMARY": _DOMAIN,
        "inventory_hostname": "h1",
        "group_names": roles,
        "groups": {role: ["h1"] for role in roles},
        **extra,
    }


def _override(provider: str) -> dict:
    return {MAIL_WRAPPER: {"services": {"email": {"provider": provider}}}}


class TestMailProviderRendersWithoutRecursion(unittest.TestCase):
    group_vars: ClassVar[dict[str, Any]]

    @classmethod
    def setUpClass(cls) -> None:
        cls.group_vars = _trusted(_GENERAL_VARS)

    def tearDown(self) -> None:
        reset_caches(files_changed=False)

    def _render(self, scope: dict, value: Any) -> Any:
        return Templar(loader=DataLoader(), variables=scope).template(value)

    def _domains(self, scope: dict) -> tuple[str, str]:
        stalwart = _trusted(_ROLES_DIR / _STALWART / ROLE_FILE_META_DOMAINS)
        mailu = _trusted(_ROLES_DIR / _MAILU / ROLE_FILE_META_DOMAINS)
        return (
            self._render(scope, stalwart["canonical"]["mail"]),
            self._render(scope, mailu["canonical"][0]),
        )

    def test_the_group_var_renders_the_wrapper_default(self) -> None:
        scope = _scope(self.group_vars, [MAIL_WRAPPER, _STALWART])
        self.assertEqual(_STALWART, self._render(scope, scope["MAIL_PROVIDER"]))

    def test_the_group_var_follows_an_inventory_override(self) -> None:
        scope = _scope(
            self.group_vars,
            [MAIL_WRAPPER, _STALWART, _MAILU],
            applications=_override(_MAILU),
        )
        self.assertEqual(_MAILU, self._render(scope, scope["MAIL_PROVIDER"]))

    def test_the_provider_domains_render_through_the_group_var(self) -> None:
        scope = _scope(self.group_vars, [MAIL_WRAPPER, _STALWART, _MAILU])
        self.assertEqual(
            (f"mail.{_DOMAIN}", f"legacy-mail.{_DOMAIN}"), self._domains(scope)
        )

    def test_an_override_moves_mail_to_the_selected_provider(self) -> None:
        scope = _scope(
            self.group_vars,
            [MAIL_WRAPPER, _STALWART, _MAILU],
            applications=_override(_MAILU),
        )
        self.assertEqual(
            (f"legacy-stalwart-mail.{_DOMAIN}", f"mail.{_DOMAIN}"),
            self._domains(scope),
        )

    def _payload_scope(self) -> dict:
        return _scope(
            self.group_vars,
            [MAIL_WRAPPER, _STALWART],
            RESOURCE_HOST_CPUS_OVERRIDE=4,
            RESOURCE_HOST_MEM_MB_OVERRIDE=64000,
        )

    def _assert_no_wrapper_domain(self, domains: dict) -> None:
        self.assertNotIn(MAIL_WRAPPER, domains)
        names = {
            str(name)
            for value in domains.values()
            for name in (value.values() if isinstance(value, dict) else value)
        }
        self.assertNotIn(f"{entity_name(MAIL_WRAPPER)}.{_DOMAIN}", names)
        self.assertIn(f"mail.{_DOMAIN}", names)

    def test_the_wrapper_enters_no_domain_map(self) -> None:
        scope = self._payload_scope()
        reset_caches(files_changed=False)
        templar = Templar(loader=DataLoader())
        applications = get_merged_applications(
            variables=scope, roles_dir=str(_ROLES_DIR), templar=templar
        )
        current_play = CanonicalDomainsFilter().canonical_domains_map(
            applications, _DOMAIN, seed=[MAIL_WRAPPER, _STALWART]
        )
        self._assert_no_wrapper_domain(current_play)
        all_domains = AllDomainsFilter().generate_all_domains(current_play, True)
        wrapper_domain = f"{entity_name(MAIL_WRAPPER)}.{_DOMAIN}"
        self.assertNotIn(wrapper_domain, all_domains)
        self.assertNotIn(f"www.{wrapper_domain}", all_domains)
        self.assertIn(f"mail.{_DOMAIN}", all_domains)
        self._assert_no_wrapper_domain(
            get_merged_domains(
                variables=scope, roles_dir=str(_ROLES_DIR), templar=templar
            )
        )

    def test_the_real_applications_payload_renders_with_the_group_var(self) -> None:
        scope = self._payload_scope()
        reset_caches(files_changed=False)
        applications = get_merged_applications(
            variables=scope,
            roles_dir=str(_ROLES_DIR),
            templar=Templar(loader=DataLoader()),
        )
        self.assertEqual(
            _STALWART, applications[MAIL_WRAPPER]["services"]["email"]["provider"]
        )
        self.assertEqual(_STALWART, self._render(scope, scope["MAIL_PROVIDER"]))


if __name__ == "__main__":
    unittest.main()
