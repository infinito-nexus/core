from __future__ import annotations

import unittest

from jinja2 import (
    ChainableUndefined,
    DictLoader,
    Environment,
    StrictUndefined,
    select_autoescape,
)

from plugins.filter.swarm.env_literal import (
    GO_TEMPLATE_OPEN,
    GO_TEMPLATE_OPEN_LITERAL,
)
from plugins.filter.swarm.env_literal import (
    FilterModule as SwarmFilters,
)
from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

ROLE = PROJECT_ROOT / "roles" / "web-app-semaphore"
TEMPLATE = ROLE / "templates" / "env.j2"
INCLUDE = "roles/sys-svc-container/templates/env.j2"
DOMAIN = "semaphore.example.org"
ORIGIN = f"https://{DOMAIN}"
OIDC_PROVIDERS_JSON = (
    '{"keycloak": {"email_claim": "{{ $member := false }}{{ range index . '
    '\\"groups\\" }}{{ $member = true }}{{ end }}{{ end }}"}}'
)


def render(source, **context):
    """Args:
        source: the text of ``templates/env.j2``, possibly planted.
        context: template variables that replace the compose form-login set.

    Returns:
        ``{key: value}`` of the rendered server env.
    """
    environment = Environment(
        loader=DictLoader({INCLUDE: "", "env.j2": source}),
        undefined=ChainableUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    environment.filters["bool"] = lambda value: (
        value is True or str(value).lower() == "true"
    )
    environment.filters["dotenv_quote"] = str
    environment.filters.update(SwarmFilters().filters())
    environment.globals["lookup"] = lambda *args, **kwargs: "stub"
    text = environment.get_template("env.j2").render(
        {
            "container_port": 3000,
            "SEMAPHORE_WEB_ROOT": ORIGIN,
            "SEMAPHORE_DEPLOY_ENABLED": False,
            "SEMAPHORE_LOGIN_FORM": True,
            "SEMAPHORE_LOGIN_2FA": False,
            "SEMAPHORE_LOGIN_SSO": False,
            "SEMAPHORE_LOGIN_LDAP": False,
            "IS_SWARM_MODE": False,
        }
        | context
    )
    return dict(line.split("=", 1) for line in text.splitlines() if "=" in line)


def token_findings(env):
    """Args:
    env: :func:`render`.

    Returns:
        Why tasks would get no token signed by the canonical origin.
    """
    findings = []
    if env.get("SEMAPHORE_JWT_ENABLED") != "true":
        findings.append(
            f"SEMAPHORE_JWT_ENABLED is {env.get('SEMAPHORE_JWT_ENABLED')!r}"
        )
    if env.get("SEMAPHORE_JWT_ISSUER") != ORIGIN:
        findings.append(f"SEMAPHORE_JWT_ISSUER is {env.get('SEMAPHORE_JWT_ISSUER')!r}")
    return findings


def oidc_providers(source, *, swarm):
    """Args:
        source: the text of ``templates/env.j2``, possibly planted.
        swarm: what ``IS_SWARM_MODE`` resolves to.

    Returns:
        The ``SEMAPHORE_OIDC_PROVIDERS`` value after swarmkit's Go template
        expansion in swarm, as rendered in compose, or ``None`` when a ``{{``
        would open a Go template action swarmkit fails or alters.
    """
    value = render(
        source,
        SEMAPHORE_LOGIN_SSO=True,
        SEMAPHORE_OIDC_PROVIDERS_JSON=OIDC_PROVIDERS_JSON,
        IS_SWARM_MODE=swarm,
    )["SEMAPHORE_OIDC_PROVIDERS"]
    if not swarm:
        return value
    texts = value.split(GO_TEMPLATE_OPEN_LITERAL)
    if any(GO_TEMPLATE_OPEN in text for text in texts):
        return None
    return GO_TEMPLATE_OPEN.join(texts)


class TestServerEnv(unittest.TestCase):
    def setUp(self):
        self.source = read_text(str(TEMPLATE))

    def test_the_server_signs_task_tokens(self):
        self.assertEqual(token_findings(render(self.source)), [])

    def test_the_issuer_is_the_canonical_origin(self):
        variables = load_yaml_str(read_text(str(ROLE / ROLE_FILE_VARS_MAIN)))
        answers = {("tls", DOMAIN, "url.origin"): ORIGIN}
        environment = Environment(
            undefined=StrictUndefined,
            autoescape=select_autoescape(default_for_string=False),
        )
        environment.globals["lookup"] = lambda *terms: answers[terms]
        self.assertEqual(
            environment.from_string(variables["SEMAPHORE_WEB_ROOT"]).render(
                SEMAPHORE_DOMAIN=DOMAIN
            ),
            ORIGIN,
        )

    def test_negative_control_tokens_off_are_reported(self):
        planted = self.source.replace(
            "SEMAPHORE_JWT_ENABLED=true", "SEMAPHORE_JWT_ENABLED=false"
        )
        self.assertNotEqual(planted, self.source)
        self.assertTrue(token_findings(render(planted)))

    def test_negative_control_another_issuer_is_reported(self):
        planted = self.source.replace(
            "SEMAPHORE_JWT_ISSUER={{ SEMAPHORE_WEB_ROOT }}",
            "SEMAPHORE_JWT_ISSUER=http://semaphore:3000",
        )
        self.assertNotEqual(planted, self.source)
        self.assertTrue(token_findings(render(planted)))

    def test_swarm_hands_the_email_claim_template_over_unexpanded(self):
        self.assertEqual(oidc_providers(self.source, swarm=True), OIDC_PROVIDERS_JSON)

    def test_compose_renders_the_providers_verbatim(self):
        self.assertEqual(oidc_providers(self.source, swarm=False), OIDC_PROVIDERS_JSON)

    def test_negative_control_an_unescaped_swarm_value_is_reported(self):
        planted = self.source.replace(
            "(SEMAPHORE_OIDC_PROVIDERS_JSON | swarm_env_literal "
            "if IS_SWARM_MODE | bool else SEMAPHORE_OIDC_PROVIDERS_JSON)",
            "SEMAPHORE_OIDC_PROVIDERS_JSON",
        )
        self.assertNotEqual(planted, self.source)
        self.assertIsNone(oidc_providers(planted, swarm=True))


if __name__ == "__main__":
    unittest.main()
