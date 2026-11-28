from __future__ import annotations

import ipaddress
import os
import re
import subprocess
import unittest
from importlib.util import module_from_spec, spec_from_file_location

from utils.cache.files import read_text

from . import PROJECT_ROOT
from ._semaphore_fake import SCRIPTS_DIR, load_project

LIB = SCRIPTS_DIR / "lib.sh"
CALLERS = ("deploy.sh", "host.sh", "monitoring.sh")
CALL = re.compile(r'(\bdomain="|DOMAIN_PRIMARY=)\$\(deploy_domain\)"')
BUILT = re.compile(r"\.ws-\$\{?WORKSPACE\b")
VECTORS = (
    (
        "wiki",
        "0b6f1c2e-3d4a-4b5c-8d6e-7f8091a2b3c4",
        "ws.example.org",
        "wiki.ws-0b6f1c2e-3d4a-4b5c-8d6e-7f8091a2b3c4.ws.example.org",
    ),
    (
        "a",
        "0a1b2c3d-0000-4000-8000-00000000000a",
        "example.com",
        "a.ws-0a1b2c3d-0000-4000-8000-00000000000a.example.com",
    ),
    (
        "shop-1",
        "ffffffff-ffff-4fff-bfff-ffffffffffff",
        "zone.platform.example.net",
        "shop-1.ws-ffffffff-ffff-4fff-bfff-ffffffffffff.zone.platform.example.net",
    ),
)
REFUSED = (
    ({"DNS_LABEL": None}, "DNS_LABEL is missing"),
    ({"DNS_LABEL": "Wiki"}, "DNS_LABEL is malformed"),
    ({"DNS_LABEL": "wiki.evil.net"}, "DNS_LABEL is malformed"),
    ({"DNS_LABEL": "-wiki"}, "DNS_LABEL is malformed"),
    ({"DNS_LABEL": "a" * 64}, "DNS_LABEL is malformed"),
    ({"WORKSPACE_DNS_ZONE": None}, "WORKSPACE_DNS_ZONE is missing"),
    ({"WORKSPACE_DNS_ZONE": "evil.net/x"}, "WORKSPACE_DNS_ZONE is malformed"),
    ({"WORKSPACE": "ws-x"}, "WORKSPACE is malformed"),
)


DOCUMENTATION = [ipaddress.ip_network("203.0.113.0/24")]


def public(_name):
    return ["203.0.113.10"]


def deploy_domain(**env):
    """Args:
    env: ``DNS_LABEL``, ``WORKSPACE`` and ``WORKSPACE_DNS_ZONE``; None drops one.

    Returns:
        The finished ``deploy_domain`` of ``lib.sh``.
    """
    return subprocess.run(
        ["bash", "-c", 'SCRIPT=lib.sh; source "$1"; deploy_domain', "_", str(LIB)],
        env={
            "PATH": os.environ["PATH"],
            **{key: value for key, value in env.items() if value is not None},
        },
        capture_output=True,
        text=True,
        check=False,
    )


def _monitoring():
    spec = spec_from_file_location(
        "monitoring_domain",
        PROJECT_ROOT / "roles/web-app-semaphore/files/python/monitoring.py",
    )
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DeployDomainTests(unittest.TestCase):
    def test_every_vector_builds_its_domain(self):
        for label, workspace, zone, domain in VECTORS:
            with self.subTest(domain=domain):
                run = deploy_domain(
                    DNS_LABEL=label, WORKSPACE=workspace, WORKSPACE_DNS_ZONE=zone
                )
                self.assertEqual((run.returncode, run.stdout), (0, f"{domain}\n"))

    def test_negative_control_a_missing_or_malformed_part_refuses(self):
        label, workspace, zone, _ = VECTORS[0]
        for overrides, message in REFUSED:
            with self.subTest(overrides=overrides):
                run = deploy_domain(
                    **{
                        "DNS_LABEL": label,
                        "WORKSPACE": workspace,
                        "WORKSPACE_DNS_ZONE": zone,
                        **overrides,
                    }
                )
                self.assertEqual((run.returncode, run.stdout), (2, ""))
                self.assertIn(f"lib.sh: {message}", run.stderr)

    def test_deploy_update_and_monitoring_take_it_from_lib_sh(self):
        for script in CALLERS:
            with self.subTest(script=script):
                self.assertRegex(read_text(str(SCRIPTS_DIR / script)), CALL)
        builders = [
            path.name
            for path in sorted(SCRIPTS_DIR.glob("*.sh"))
            if path != LIB and BUILT.search(read_text(str(path)))
        ]
        self.assertEqual(builders, [])

    def test_every_template_that_reads_the_domain_asks_the_store_for_the_label(self):
        project = load_project()
        surveys = {
            entry["name"]: dict(entry["survey"])
            for entry in (*project.WORKSPACE_TEMPLATES, *project.WORKSPACES_TEMPLATES)
        }
        self.assertEqual(
            {
                name: surveys[name].get("DNS_LABEL")
                for name in ("deploy", "update", "release", "monitoring")
            },
            {"deploy": True, "update": False, "release": None, "monitoring": False},
        )
        self.assertEqual(
            [
                name
                for name, survey in surveys.items()
                if "WORKSPACE_DNS_ZONE" in survey
            ],
            [],
        )

    def test_monitoring_federates_on_the_deploy_domain_only(self):
        monitoring = _monitoring()
        for _, workspace, _, domain in VECTORS:
            variables = {
                "ansible_host": "203.0.113.10",
                "DOMAIN_PRIMARY": "evil.example.net",
                "platform_monitoring": {"agent": False},
            }
            with self.subTest(domain=domain):
                entry = monitoring.plan(
                    workspace,
                    "apply",
                    "target",
                    {"_meta": {"hostvars": {"target": variables}}},
                    DOCUMENTATION,
                    domain,
                    public,
                )["entry"]
                self.assertEqual(entry["federation"], f"prometheus.{domain}")
                self.assertNotIn("evil.example.net", entry["domains"])
                self.assertIn(domain, entry["domains"])

    def test_negative_control_monitoring_refuses_a_malformed_deploy_domain(self):
        monitoring = _monitoring()
        variables = {"ansible_host": "203.0.113.10", "DOMAIN_PRIMARY": "ok.example.org"}
        for primary in ("", "Wiki.example.org", "x"):
            with (
                self.subTest(primary=primary),
                self.assertRaises(monitoring.RefusalError),
            ):
                monitoring.plan(
                    VECTORS[0][1],
                    "apply",
                    "target",
                    {"_meta": {"hostvars": {"target": variables}}},
                    DOCUMENTATION,
                    primary,
                    public,
                )


if __name__ == "__main__":
    unittest.main()
