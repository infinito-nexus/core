from __future__ import annotations

import functools
import importlib.util
import unittest
import unittest.mock as mock

from ansible.parsing.dataloader import DataLoader
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase
from ansible.template import Templar

from plugins.lookup.network_redirects import LookupModule as NetworkRedirectsLookup
from plugins.lookup.network_siblings import served_siblings
from utils.cache.domains import _inject_network_siblings
from utils.cache.files import PROJECT_ROOT
from utils.domains.default_primary import default_domain_primary
from utils.domains.list import load_yaml_mapping, render_domain_value
from utils.roles.mapping import (
    ROLE_FILE_META_DOMAINS,
    ROLE_FILE_META_NETWORKS,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_VARS_MAIN,
)

ROLE_DIR = PROJECT_ROOT / "roles" / "sys-ctl-hlth-csp"
VARS = ROLE_DIR / ROLE_FILE_VARS_MAIN
SCRIPT = ROLE_DIR / "files" / "python" / "script.py"
SERVED_ROLES = ("svc-prx-openresty", "web-app-dashboard", "web-svc-html")

PRIMARY = default_domain_primary()
NODE = "a" * 56 + ".onion"
HOMEPAGE = f"dashboard.{PRIMARY}"
HTML = f"html.{PRIMARY}"
HTML_ONION = f"html.{NODE}"


def _role_entry(role: str) -> tuple[list[str], dict]:
    """Read the canonical domains and the network config of one real role.

    Args:
        role: the role directory name.

    Returns:
        ``(canonical, config)``: the rendered ``domains.canonical`` and the
        ``services.tor`` and ``networks`` the domain map reads.
    """
    role_dir = PROJECT_ROOT / "roles" / role
    domains = load_yaml_mapping(role_dir / ROLE_FILE_META_DOMAINS)
    canonical = render_domain_value(
        domains["canonical"], {"DOMAIN_PRIMARY": PRIMARY}, f"{role}.canonical"
    )
    config = {
        "services": {
            "tor": load_yaml_mapping(role_dir / ROLE_FILE_META_SERVICES)["tor"]
        }
    }
    networks = role_dir / ROLE_FILE_META_NETWORKS
    if networks.exists():
        config["networks"] = load_yaml_mapping(networks)
    return canonical, config


@functools.cache
def _domain_map() -> dict:
    """The multi-network domain map of ``SERVED_ROLES`` on a Tor node."""
    entries = {role: _role_entry(role) for role in SERVED_ROLES}
    variables = {"group_names": ["svc-net-tor", *SERVED_ROLES]}
    return _inject_network_siblings(
        {role: canonical for role, (canonical, _config) in entries.items()},
        {role: config for role, (_canonical, config) in entries.items()},
        PRIMARY,
        NODE,
        "multi",
        templar=Templar(loader=DataLoader(), variables=variables),
        variables=variables,
    )


def siblings(domain: str) -> list[str]:
    """``network_siblings`` of ``domain`` over the real ``_domain_map``.

    Args:
        domain: the domain a redirect names.
    """
    return served_siblings(domain, _domain_map(), PRIMARY, NODE)


class _Stub(LookupBase):
    def __init__(self, answer):
        super().__init__()
        self._answer = answer

    def run(self, terms, variables=None, **kwargs):
        return [self._answer(*terms, **kwargs)]


def skip_domains(redirects: list[dict[str, str]], served: list[str]) -> list[str]:
    """Resolve ``HEALTH_CSP_SKIP_DOMAINS`` of ``vars/main.yml``.

    Args:
        redirects: ``CURRENT_PLAY_REDIRECT_DOMAINS`` of the round.
        served: ``CURRENT_PLAY_DOMAINS_ALL`` of the round.

    Returns:
        The rendered skip list, with the real ``network_redirects`` lookup
        fanning ``redirects`` out over ``siblings``.
    """
    stubs = {
        "network_siblings": siblings,
        "deployment": lambda: {"deployed": ["web-svc-html"]},
        "csp_skip_domains": lambda **_kwargs: [],
    }
    real_get = lookup_loader.get

    def get(name, *args, **kwargs):
        if name == "network_redirects":
            lookup = NetworkRedirectsLookup()
            lookup._loader = kwargs.get("loader")
            return lookup
        if name in stubs:
            return _Stub(stubs[name])
        return real_get(name, *args, **kwargs)

    declared = DataLoader().load_from_file(str(VARS), trusted_as_template=True)
    variables = {
        "CURRENT_PLAY_REDIRECT_DOMAINS": redirects,
        "CURRENT_PLAY_DOMAINS_ALL": served,
    }
    templar = Templar(loader=DataLoader(), variables={**declared, **variables})
    with mock.patch.object(lookup_loader, "get", side_effect=get):
        return list(templar.template(declared["HEALTH_CSP_SKIP_DOMAINS"]))


def _script():
    spec = importlib.util.spec_from_file_location("csp_skip_wrapper", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestTheRealSiblingsOfTheRound(unittest.TestCase):
    def test_the_node_onion_is_a_sibling_of_the_primary_domain(self) -> None:
        self.assertEqual(
            siblings(PRIMARY),
            [PRIMARY, NODE],
            "svc-prx-openresty serves the bare primary domain on both networks, "
            "so network_redirects fans the apex redirect out to the node onion",
        )

    def test_the_homepage_has_an_onion_sibling(self) -> None:
        self.assertEqual(siblings(HOMEPAGE), [HOMEPAGE, f"dashboard.{NODE}"])

    def test_the_deployed_app_has_an_onion_sibling(self) -> None:
        self.assertEqual(siblings(HTML), [HTML, HTML_ONION])


class TestSkipDomainsFollowTheRedirectFanOut(unittest.TestCase):
    def test_the_onion_apex_of_an_unserved_homepage_is_skipped(self) -> None:
        skipped = skip_domains(
            [{"source": PRIMARY, "target": HOMEPAGE}], [HTML, HTML_ONION, PRIMARY]
        )
        self.assertEqual(
            skipped,
            [PRIMARY, NODE],
            "web-opt-rdr-domains renders the node onion apex as a network "
            "sibling of the clearnet apex, with the same undeployed target, so "
            "the probe must skip it for the same reason",
        )

    def test_an_onion_app_vhost_stays_under_probe(self) -> None:
        skipped = skip_domains(
            [{"source": PRIMARY, "target": HOMEPAGE}], [HTML, HTML_ONION, PRIMARY]
        )
        self.assertNotIn(HTML_ONION, skipped)

    def test_a_redirect_to_a_served_target_stays_under_probe(self) -> None:
        self.assertEqual(
            skip_domains(
                [{"source": PRIMARY, "target": HTML}], [HTML, HTML_ONION, PRIMARY]
            ),
            [],
        )

    def test_a_round_without_redirects_skips_nothing(self) -> None:
        self.assertEqual(skip_domains([], [HTML, HTML_ONION]), [])


class TestABrokenOnionVhostStaysRed(unittest.TestCase):
    def test_the_onion_batch_failure_fails_the_service(self) -> None:
        script = _script()
        vhosts = dict.fromkeys((PRIMARY, NODE, HTML, HTML_ONION))
        argv = [
            "script.py",
            "--nginx-config-dir=/etc/nginx/servers",
            "--proxy-suffix=.onion",
            "--image=img:tag",
            "--tor-proxy=socks5://127.0.0.1:9050",
            "--skip-domain",
            *skip_domains(
                [{"source": PRIMARY, "target": HOMEPAGE}], [HTML, HTML_ONION, PRIMARY]
            ),
        ]
        with (
            mock.patch.object(script, "collect_vhosts", return_value=vhosts),
            mock.patch.object(
                script,
                "build_urls_from_nginx_confs",
                side_effect=lambda _vhosts, domains: [f"http://{d}/" for d in domains],
            ),
            mock.patch.object(
                script,
                "run_checker",
                side_effect=lambda **kwargs: 1 if kwargs["proxy"] else 0,
            ) as checker,
            mock.patch.object(script.sys, "argv", argv),
            self.assertRaises(SystemExit) as raised,
        ):
            script.main()

        onion_urls = [
            url
            for call in checker.call_args_list
            if call.kwargs["proxy"]
            for url in call.kwargs["urls"]
        ]
        self.assertEqual(onion_urls, [f"http://{HTML_ONION}/"])
        self.assertEqual(raised.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
