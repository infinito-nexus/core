from __future__ import annotations

import unittest
from unittest import mock

from ansible.parsing.dataloader import DataLoader
from ansible.plugins.loader import filter_loader, lookup_loader
from ansible.plugins.lookup import LookupBase
from ansible.template import Templar, trust_as_template

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.networks.reachability import CLEARNET, TOR, network_of
from utils.roles.mapping import ROLE_FILE_TASKS_MAIN

filter_loader.add_directory(str(PROJECT_ROOT / "plugins" / "filter"))
lookup_loader.add_directory(str(PROJECT_ROOT / "plugins" / "lookup"))

SHALLOW = "lookup('template_shallow', "
BUILTIN = "lookup('template', "
DOMAIN = "infinito.example"
ONION = "a" * 56 + ".onion"
APP_DOMAIN = {CLEARNET: f"next.cloud.{DOMAIN}", TOR: f"next.cloud.{ONION}"}
BASE_URL = {
    "web-app-matomo": {
        CLEARNET: f"https://matomo.{DOMAIN}/",
        TOR: f"http://matomo.{ONION}/",
    },
    "web-svc-logout": {
        CLEARNET: f"https://logout.{DOMAIN}/",
        TOR: f"http://logout.{ONION}/",
    },
    "web-app-dashboard": {
        CLEARNET: f"https://dash.{DOMAIN}/",
        TOR: f"http://dash.{ONION}/",
    },
}
INJECTORS = {
    "logout": ("sys-front-inj-logout", ROLE_FILE_TASKS_MAIN, "logout_code"),
    "dashboard": ("sys-front-inj-dashboard", ROLE_FILE_TASKS_MAIN, "iframe_init_code"),
    "matomo": ("sys-front-inj-matomo", "tasks/inject.yml", "matomo_tracking_code"),
}
OIDC = {
    "CLIENT": {
        "LOGOUT_URL": "https://auth.example/realms/x/protocol/openid-connect/logout",
        "ID": "infinito",
    }
}


class _Stub(LookupBase):
    def __init__(self, answer):
        super().__init__()
        self._answer = answer

    def run(self, terms, variables=None, **kwargs):
        return [self._answer(variables, *terms)]


def _tls(variables, application_id, key):
    if key != "url.base":
        raise AssertionError(f"unexpected tls key: {key!r}")
    return BASE_URL[application_id][network_of(variables["domain"])]


def _config(variables, application_id, key, default):
    if (application_id, key) != ("svc-net-tor", "services.tor.node"):
        raise AssertionError(f"unexpected config key: {application_id!r} {key!r}")
    return variables["_tor_node"]


STUBS = {
    "tls": _tls,
    "domain": lambda variables, application_id: variables["_canonical"],
    "config": _config,
}


def load_expression(injector: str) -> str:
    """Return the set_fact expression of an injector's code-loading task.

    Args:
        injector: a key of ``INJECTORS``.

    Returns:
        The templated value that renders the injector's code.
    """
    role, tasks_file, fact = INJECTORS[injector]
    tasks = load_yaml_any(str(PROJECT_ROOT / "roles" / role / tasks_file))
    [task] = [t for t in tasks if fact in t.get("set_fact", {})]
    return task["set_fact"][fact]


def render(injector: str, expression: str, variables: dict):
    """Render an injector expression with stubbed inventory lookups.

    Args:
        injector: a key of ``INJECTORS``.
        expression: the set_fact value to template.
        variables: the task variables, without the search path.

    Returns:
        ``("code", text)`` on success, else ``("error", causes)`` with the
        unaltered message of every exception in the cause chain.
    """
    role = INJECTORS[injector][0]
    real_get = lookup_loader.get

    def get(name, *args, **kwargs):
        if name in STUBS:
            return _Stub(STUBS[name])
        return real_get(name, *args, **kwargs)

    scope = {
        **variables,
        "ansible_search_path": [str(PROJECT_ROOT / "roles" / role)],
    }
    try:
        with mock.patch.object(lookup_loader, "get", side_effect=get):
            code = Templar(loader=DataLoader(), variables=scope).template(
                trust_as_template(expression)
            )
    except Exception as error:
        causes = []
        while error is not None:
            causes.append(f"{type(error).__name__}: {error}")
            error = error.__cause__
        return ("error", causes)
    return ("code", code)


def _variants(injector: str) -> list[dict]:
    variants = []
    for network in (CLEARNET, TOR):
        for debug in (True, False):
            base = {
                "domain": APP_DOMAIN[network],
                "application_id": "web-app-nextcloud",
                "MODE_DEBUG": debug,
                "DOMAIN_PRIMARY": DOMAIN,
            }
            if injector == "logout":
                for canonical in APP_DOMAIN.values():
                    variants.append({**base, "OIDC": OIDC, "_canonical": canonical})
                    variants.append(
                        {
                            **base,
                            "OIDC": OIDC,
                            "_canonical": canonical,
                            "OIDC_OVERRIDE": {"URL": "https://idp.example"},
                        }
                    )
            elif injector == "dashboard":
                variants.extend({**base, "_tor_node": node} for node in ("", ONION))
            else:
                variants.extend(
                    {
                        **base,
                        "matomo_site_domain": APP_DOMAIN[network],
                        "matomo_tracking_scope": scope,
                        "matomo_site_id": 7,
                    }
                    for scope in ("root", "domain")
                )
    return variants


BROKEN = {
    "logout": {
        "domain": APP_DOMAIN[TOR],
        "application_id": "x",
        "MODE_DEBUG": False,
        "_canonical": DOMAIN,
    },
    "dashboard": {"domain": APP_DOMAIN[TOR], "_tor_node": ""},
    "matomo": {
        "domain": APP_DOMAIN[CLEARNET],
        "matomo_tracking_scope": "root",
        "MODE_DEBUG": False,
    },
}


class TestInjectorCodeRendersShallow(unittest.TestCase):
    def test_every_code_loading_task_uses_the_shallow_lookup(self) -> None:
        for injector in INJECTORS:
            with self.subTest(injector=injector):
                expression = load_expression(injector)
                self.assertIn(SHALLOW, expression)
                self.assertNotIn(BUILTIN, expression)

    def test_every_variant_renders_byte_identical_code(self) -> None:
        for injector in INJECTORS:
            shallow = load_expression(injector)
            builtin = shallow.replace(SHALLOW, BUILTIN)
            for variables in _variants(injector):
                with self.subTest(injector=injector, variables=variables):
                    outcome = render(injector, shallow, variables)
                    self.assertEqual(outcome[0], "code", outcome)
                    self.assertEqual(outcome, render(injector, builtin, variables))

    def test_the_variants_reach_every_branch(self) -> None:
        shallow = load_expression("logout")
        codes = {render("logout", shallow, v)[1] for v in _variants("logout")}
        self.assertTrue(any("post_logout_redirect_uri" in code for code in codes))
        self.assertTrue(any("post_logout_redirect_uri" not in code for code in codes))
        shallow = load_expression("matomo")
        codes = {render("matomo", shallow, v)[1] for v in _variants("matomo")}
        self.assertTrue(any("enableCrossDomainLinking" in code for code in codes))
        self.assertTrue(any("Matomo is loaded" in code for code in codes))
        shallow = load_expression("dashboard")
        codes = {render("dashboard", shallow, v)[1] for v in _variants("dashboard")}
        self.assertTrue(any(f"'{ONION}'" in code for code in codes))

    def test_a_missing_variable_fails_with_the_builtin_message(self) -> None:
        for injector, variables in BROKEN.items():
            with self.subTest(injector=injector):
                shallow = load_expression(injector)
                outcome = render(injector, shallow, variables)
                self.assertEqual(outcome[0], "error", outcome)
                self.assertIn("is undefined", " ".join(outcome[1]))
                self.assertEqual(
                    outcome,
                    render(injector, shallow.replace(SHALLOW, BUILTIN), variables),
                )


if __name__ == "__main__":
    unittest.main()
