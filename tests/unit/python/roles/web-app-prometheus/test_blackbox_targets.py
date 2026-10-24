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
}
TLS_MODES = {
    "web-app-nextcloud": "off",
    "web-app-gitea": "self_signed",
    "web-app-matrix": "letsencrypt",
}
ROLES_WITH_THE_PROMETHEUS_SERVICE = [
    "web-app-nextcloud",
    "web-app-gitea",
    "web-app-matrix",
]
SHARED_JITSI = {"jitsi": {"enabled": True, "shared": True, "domains": ["jitsi"]}}


def probed_groups(
    *, ca_injected: bool, matrix_services: dict | None = None
) -> dict[str, dict]:
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
    return {
        group["labels"]["app"]: group
        for group in jobs["blackbox-healthz"]["static_configs"]
    }


def probed_targets(matrix_services: dict | None = None) -> dict[str, list[str]]:
    return {
        app: group["targets"]
        for app, group in probed_groups(
            ca_injected=True, matrix_services=matrix_services
        ).items()
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
        labels = probed_groups(ca_injected=False)["web-app-gitea"]["labels"]
        self.assertEqual(labels["__param_module"], "http_ready_private_ca")

    def test_a_publicly_trusted_target_is_verified_while_the_ca_is_missing(self):
        labels = probed_groups(ca_injected=False)["web-app-matrix"]["labels"]
        self.assertNotIn("__param_module", labels)

    def test_a_plain_http_target_keeps_the_verifying_module(self):
        labels = probed_groups(ca_injected=False)["web-app-nextcloud"]["labels"]
        self.assertNotIn("__param_module", labels)

    def test_every_target_is_verified_once_the_ca_is_mounted(self):
        groups = probed_groups(ca_injected=True)
        self.assertEqual(
            [
                app
                for app, group in groups.items()
                if "__param_module" in group["labels"]
            ],
            [],
        )


if __name__ == "__main__":
    unittest.main()
