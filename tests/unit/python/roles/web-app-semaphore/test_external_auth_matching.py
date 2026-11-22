from __future__ import annotations

import unittest

import jinja2

from utils.cache.files import PROJECT_ROOT, read_text

ENV_TEMPLATE = "roles/web-app-semaphore/templates/env.j2"
INCLUDED = "roles/sys-svc-container/templates/env.j2"
MATCHING = "SEMAPHORE_EXTERNAL_AUTH_EMAIL_MATCHING=always"


def render(*, oidc: bool, ldap: bool) -> list[str]:
    """
    Args:
        oidc: what ``SEMAPHORE_OIDC_ENABLED`` resolves to.
        ldap: what ``SEMAPHORE_LDAP_ENABLED`` resolves to.

    Returns:
        The rendered lines.
    """
    source = read_text(str(PROJECT_ROOT / ENV_TEMPLATE))
    environment = jinja2.Environment(
        loader=jinja2.DictLoader({ENV_TEMPLATE: source, INCLUDED: ""}),
        undefined=jinja2.ChainableUndefined,
    )
    environment.filters["bool"] = bool
    environment.filters["dotenv_quote"] = str
    environment.globals["lookup"] = lambda *_args, **_kwargs: ""
    rendered = environment.get_template(ENV_TEMPLATE).render(
        SEMAPHORE_OIDC_ENABLED=oidc,
        SEMAPHORE_LDAP_ENABLED=ldap,
    )
    return rendered.splitlines()


class TestExternalAuthMatching(unittest.TestCase):
    def test_both_providers_match_one_user(self) -> None:
        self.assertIn(MATCHING, render(oidc=True, ldap=True))

    def test_a_single_provider_keeps_the_default(self) -> None:
        for oidc, ldap in ((True, False), (False, True), (False, False)):
            with self.subTest(oidc=oidc, ldap=ldap):
                lines = render(oidc=oidc, ldap=ldap)
                self.assertFalse(
                    any(
                        line.startswith("SEMAPHORE_EXTERNAL_AUTH_EMAIL_MATCHING")
                        for line in lines
                    )
                )


if __name__ == "__main__":
    unittest.main()
