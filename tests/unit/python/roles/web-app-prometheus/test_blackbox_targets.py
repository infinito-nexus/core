from __future__ import annotations

import unittest

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml_str
from utils.domains.default_primary import default_domain_primary
from utils.domains.unserved import served_domains

TEMPLATE_DIR = PROJECT_ROOT / "roles/web-app-prometheus/templates/configuration"
ONION = "a" * 56 + ".onion"
DOMAIN = default_domain_primary()

DOMAINS = {
    "web-app-prometheus": [f"prometheus.{ONION}"],
    "web-app-nextcloud": {"nextcloud": f"next.cloud.{ONION}"},
    "web-app-gitea": [f"git.{DOMAIN}"],
    "web-app-matrix": {
        "synapse": f"matrix.{DOMAIN}",
        "jitsi": f"jitsi.matrix.{DOMAIN}",
        "jitsi_onion": f"jitsi.matrix.{ONION}",
    },
    "web-svc-cdn": [f"cdn.{DOMAIN}"],
    "svc-db-postgres": [f"postgres.{DOMAIN}"],
    "web-app-docs": [f"docs.{DOMAIN}", f"docs.{ONION}"],
}
TLS_MODES = {
    f"next.cloud.{ONION}": "off",
    f"git.{DOMAIN}": "self_signed",
    f"matrix.{DOMAIN}": "letsencrypt",
    f"jitsi.matrix.{DOMAIN}": "letsencrypt",
    f"jitsi.matrix.{ONION}": "off",
    f"docs.{DOMAIN}": "self_signed",
    f"docs.{ONION}": "off",
}
ROLES_WITH_THE_PROMETHEUS_SERVICE = [
    "web-app-nextcloud",
    "web-app-gitea",
    "web-app-matrix",
    "web-app-docs",
]
SHARED_JITSI = {"jitsi": {"enabled": True, "shared": True, "domains": ["jitsi"]}}


def probed_groups(
    *, ca_injected: bool, matrix_services: dict | None = None
) -> dict[str, list[dict]]:
    services = {
        "web-app-matrix": SHARED_JITSI if matrix_services is None else matrix_services
    }

    def lookup(name, *terms, **_kwargs):
        if name == "domains":
            return DOMAINS
        if name == "config":
            app, key = terms
            assert key == "services"
            return services.get(app, {})
        if name == "roles_with_service":
            return [{"id": role} for role in ROLES_WITH_THE_PROMETHEUS_SERVICE]
        if name == "ca_injected":
            return ca_injected
        if name == "tls":
            term, want = terms
            if want == "mode":
                return TLS_MODES[term]
            scheme = "http" if term.endswith(".onion") else "https"
            return {
                "url.base": f"{scheme}://{term}/",
                "protocols.web": "http",
                "enabled": False,
            }[want]
        if name == "domain":
            return DOMAINS[terms[0]][0]
        if name == "scrape_target":
            return f"{terms[1]}:9000"
        if name == "native_metrics_apps":
            return []
        raise AssertionError(f"the template calls an unexpected lookup: {name!r}")

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        undefined=StrictUndefined,
        autoescape=select_autoescape(),
    )
    env.filters["bool"] = bool
    env.filters["served_domains"] = served_domains
    rendered = env.get_template("prometheus.yml.j2").render(
        lookup=lookup,
        application_id="web-app-prometheus",
        CURRENT_PLAY_APPLICATIONS=list(DOMAINS),
        DOMAIN_PRIMARY=DOMAIN,
        ALERT_RULES_CONFIG_DOCKER="/etc/prometheus/alert_rules.yml",
    )
    jobs = {job["job_name"]: job for job in load_yaml_str(rendered)["scrape_configs"]}
    groups: dict[str, list[dict]] = {}
    for group in jobs["blackbox-healthz"]["static_configs"]:
        groups.setdefault(group["labels"]["app"], []).append(group)
    return groups


def probed_targets(matrix_services: dict | None = None) -> dict[str, list[str]]:
    return {
        app: [target for group in groups for target in group["targets"]]
        for app, groups in probed_groups(
            ca_injected=True, matrix_services=matrix_services
        ).items()
    }


def modules(app: str, *, ca_injected: bool) -> dict[str, str | None]:
    return {
        target: group["labels"].get("__param_module")
        for group in probed_groups(ca_injected=ca_injected)[app]
        for target in group["targets"]
    }


class TestBlackboxTargets(unittest.TestCase):
    def test_an_onion_app_is_probed_under_its_onion_name_over_http(self):
        self.assertEqual(
            probed_targets()["web-app-nextcloud"],
            [f"http://next.cloud.{ONION}/healthz/ready"],
        )

    def test_a_clearnet_app_is_probed_under_its_own_scheme(self):
        self.assertEqual(
            probed_targets()["web-app-gitea"],
            [f"https://git.{DOMAIN}/healthz/ready"],
        )

    def test_a_shared_service_domain_and_its_onion_mirror_are_not_probed(self):
        self.assertEqual(
            probed_targets()["web-app-matrix"],
            [f"https://matrix.{DOMAIN}/healthz/ready"],
        )

    def test_a_disabled_service_domain_is_not_probed(self):
        disabled = {"jitsi": {"enabled": False, "shared": False, "domains": ["jitsi"]}}
        self.assertEqual(
            probed_targets(disabled)["web-app-matrix"],
            [f"https://matrix.{DOMAIN}/healthz/ready"],
        )

    def test_an_own_service_domain_is_probed(self):
        own = {"jitsi": {"enabled": True, "shared": False, "domains": ["jitsi"]}}
        self.assertEqual(
            probed_targets(own)["web-app-matrix"],
            [
                f"https://matrix.{DOMAIN}/healthz/ready",
                f"https://jitsi.matrix.{DOMAIN}/healthz/ready",
                f"http://jitsi.matrix.{ONION}/healthz/ready",
            ],
        )

    def test_only_the_roles_the_service_lookup_names_are_probed(self):
        self.assertEqual(set(probed_targets()), set(ROLES_WITH_THE_PROMETHEUS_SERVICE))

    def test_a_private_ca_target_skips_verification_while_the_ca_is_missing(self):
        self.assertEqual(
            modules("web-app-gitea", ca_injected=False),
            {f"https://git.{DOMAIN}/healthz/ready": "http_ready_private_ca"},
        )

    def test_a_publicly_trusted_target_is_verified_while_the_ca_is_missing(self):
        self.assertEqual(
            modules("web-app-matrix", ca_injected=False),
            {f"https://matrix.{DOMAIN}/healthz/ready": None},
        )

    def test_a_plain_http_target_keeps_the_verifying_module(self):
        self.assertEqual(
            modules("web-app-nextcloud", ca_injected=False),
            {f"http://next.cloud.{ONION}/healthz/ready": None},
        )

    def test_each_sibling_is_judged_by_its_own_tls_mode(self):
        self.assertEqual(
            modules("web-app-docs", ca_injected=False),
            {
                f"https://docs.{DOMAIN}/healthz/ready": "http_ready_private_ca",
                f"http://docs.{ONION}/healthz/ready": None,
            },
        )

    def test_every_target_is_verified_once_the_ca_is_mounted(self):
        self.assertEqual(
            [
                app
                for app, groups in probed_groups(ca_injected=True).items()
                for group in groups
                if "__param_module" in group["labels"]
            ],
            [],
        )


if __name__ == "__main__":
    unittest.main()
