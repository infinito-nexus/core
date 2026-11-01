from __future__ import annotations

import contextlib
import datetime as dt
import importlib.util
import io
import json
import re
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase, main, mock

from . import PROJECT_ROOT


def _load_script():
    path = (
        PROJECT_ROOT
        / "roles"
        / "sys-ctl-hlth-runtime"
        / "files"
        / "python"
        / "script.py"
    )
    spec = importlib.util.spec_from_file_location("hlth_runtime_script", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


SCRIPT = _load_script()
MARKER = SCRIPT.PROBE_MARKER
TODAY = dt.date(2026, 10, 31)
JAMMY_PHP = "8.1.2-1ubuntu2.28"

TRIVY_HOST = {
    "SchemaVersion": 2,
    "ArtifactName": "/host",
    "ArtifactType": "filesystem",
    "Results": [
        {
            "Target": "/host (ubuntu 22.04)",
            "Class": "os-pkgs",
            "Type": "ubuntu",
            "Vulnerabilities": [
                {
                    "VulnerabilityID": "CVE-2022-3602",
                    "PkgName": "libssl3",
                    "InstalledVersion": "3.0.2-0ubuntu1",
                    "FixedVersion": "3.0.2-0ubuntu1.7",
                    "Status": "fixed",
                    "Severity": "HIGH",
                },
                {
                    "VulnerabilityID": "CVE-2017-7189",
                    "PkgName": "php8.1-cli",
                    "InstalledVersion": JAMMY_PHP,
                    "Status": "affected",
                    "Severity": "LOW",
                },
            ],
        },
        {
            "Target": "Node.js",
            "Class": "lang-pkgs",
            "Type": "node-pkg",
            "Vulnerabilities": [
                {
                    "VulnerabilityID": "CVE-2021-44906",
                    "VendorIDs": ["GHSA-xvch-5gv4-984h"],
                    "PkgName": "minimist",
                    "InstalledVersion": "1.2.0",
                    "FixedVersion": "1.2.6, 0.2.4",
                    "Status": "fixed",
                    "Severity": "CRITICAL",
                }
            ],
        },
    ],
}

GRYPE_HOST = {
    "matches": [
        {
            "vulnerability": {
                "id": "CVE-2022-3602",
                "namespace": "ubuntu:distro:ubuntu:22.04",
                "severity": "High",
                "fix": {"versions": ["3.0.2-0ubuntu1.7"], "state": "fixed"},
            },
            "relatedVulnerabilities": [{"id": "CVE-2022-3602", "namespace": "nvd:cpe"}],
            "artifact": {"name": "libssl3", "version": "3.0.2-0ubuntu1", "type": "deb"},
        },
        {
            "vulnerability": {
                "id": "GHSA-p6mc-m468-83gw",
                "namespace": "github:language:javascript",
                "severity": "High",
                "fix": {"versions": ["4.17.19"], "state": "fixed"},
            },
            "relatedVulnerabilities": [{"id": "CVE-2020-8203", "namespace": "nvd:cpe"}],
            "artifact": {"name": "lodash", "version": "4.17.15", "type": "npm"},
        },
        {
            "vulnerability": {
                "id": "CVE-2017-7189",
                "namespace": "ubuntu:distro:ubuntu:22.04",
                "severity": "Low",
                "fix": {"versions": [], "state": "not-fixed"},
            },
            "relatedVulnerabilities": [{"id": "CVE-2017-7189", "namespace": "nvd:cpe"}],
            "artifact": {"name": "php8.1-cli", "version": JAMMY_PHP, "type": "deb"},
        },
    ],
    "distro": {"name": "ubuntu", "version": "22.04", "idLike": ["debian"]},
}

OSV_SOURCE = "/work/host.osv.cdx.json"
OSV_HOST = {
    "results": [
        {
            "source": {"path": OSV_SOURCE, "type": "sbom"},
            "packages": [
                {
                    "package": {
                        "name": "lodash",
                        "version": "4.17.15",
                        "ecosystem": "npm",
                    },
                    "vulnerabilities": [
                        {
                            "id": "GHSA-p6mc-m468-83gw",
                            "aliases": ["CVE-2020-8203"],
                            "affected": [
                                {
                                    "package": {"name": "lodash", "ecosystem": "npm"},
                                    "ranges": [
                                        {
                                            "type": "SEMVER",
                                            "events": [
                                                {"introduced": "3.7.0"},
                                                {"fixed": "4.17.19"},
                                            ],
                                        }
                                    ],
                                },
                                {
                                    "package": {
                                        "name": "lodash-es",
                                        "ecosystem": "npm",
                                    },
                                    "ranges": [
                                        {
                                            "type": "SEMVER",
                                            "events": [
                                                {"introduced": "0"},
                                                {"fixed": "4.17.20"},
                                            ],
                                        }
                                    ],
                                },
                            ],
                        }
                    ],
                    "groups": [
                        {
                            "ids": ["GHSA-p6mc-m468-83gw"],
                            "aliases": ["CVE-2020-8203", "GHSA-p6mc-m468-83gw"],
                            "max_severity": "7.4",
                        }
                    ],
                },
                {
                    "package": {
                        "name": "openssl",
                        "version": "3.0.2-0ubuntu1",
                        "ecosystem": "Ubuntu:22.04:LTS",
                    },
                    "vulnerabilities": [
                        {
                            "id": "UBUNTU-CVE-2022-1292",
                            "upstream": ["CVE-2022-1292"],
                            "affected": [
                                {
                                    "package": {
                                        "name": "openssl",
                                        "ecosystem": "Ubuntu:22.04:LTS",
                                    },
                                    "ranges": [
                                        {
                                            "type": "ECOSYSTEM",
                                            "events": [
                                                {"introduced": "0"},
                                                {"fixed": "3.0.2-0ubuntu1.1"},
                                            ],
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                    "groups": [
                        {
                            "ids": ["USN-5402-1", "UBUNTU-CVE-2022-1292"],
                            "aliases": [
                                "CVE-2022-1292",
                                "UBUNTU-CVE-2022-1292",
                                "USN-5402-1",
                            ],
                            "max_severity": "9.8",
                        }
                    ],
                },
                {
                    "package": {
                        "name": "php8.1",
                        "version": JAMMY_PHP,
                        "ecosystem": "Ubuntu:22.04:LTS",
                    },
                    "vulnerabilities": [
                        {
                            "id": "UBUNTU-CVE-2017-7189",
                            "upstream": ["CVE-2017-7189"],
                            "affected": [
                                {
                                    "package": {
                                        "name": "php8.1",
                                        "ecosystem": "Ubuntu:22.04:LTS",
                                    },
                                    "ranges": [
                                        {
                                            "type": "ECOSYSTEM",
                                            "events": [{"introduced": "0"}],
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                    "groups": [
                        {
                            "ids": ["UBUNTU-CVE-2017-7189"],
                            "aliases": ["CVE-2017-7189", "UBUNTU-CVE-2017-7189"],
                            "max_severity": "7.5",
                        }
                    ],
                },
            ],
        }
    ]
}

SYFT_PHP_IMAGE = {
    "artifacts": [
        {
            "id": "a1",
            "name": "curl",
            "version": "8.22.0-r0",
            "type": "apk",
            "purl": "pkg:apk/alpine/curl@8.22.0-r0",
        },
        {
            "id": "a2",
            "name": "php-cli",
            "version": "8.4.26",
            "type": "binary",
            "foundBy": "php-interpreter-cataloger",
            "purl": "pkg:generic/php-cli@8.4.26",
            "cpes": [
                {
                    "cpe": "cpe:2.3:a:php:php:8.4.26:*:*:*:*:*:*:*",
                    "source": "nvd-cpe-dictionary",
                }
            ],
            "locations": [{"path": "/usr/local/bin/php"}],
        },
    ],
    "artifactRelationships": [{"parent": "a1", "child": "f1", "type": "contains"}],
    "files": [{"id": "f1", "location": {"path": "/usr/bin/curl"}}],
    "source": {"type": "image", "metadata": {"userInput": "php:8.4.26-cli-alpine"}},
    "distro": {"id": "alpine", "versionID": "3.24.2"},
    "descriptor": {"name": "syft", "version": "1.55.0"},
    "schema": {"version": "16.1.11"},
}

GRYPE_PHP_RUNTIME = {
    "matches": [
        {
            "vulnerability": {
                "id": "CVE-2026-109618",
                "namespace": "nvd:cpe",
                "severity": "Critical",
                "fix": {
                    "versions": ["8.2.35", "8.3.36", "8.4.27", "8.5.12"],
                    "state": "fixed",
                },
            },
            "relatedVulnerabilities": [],
            "artifact": {"name": "php-cli", "version": "8.4.26", "type": "binary"},
        },
        {
            "vulnerability": {
                "id": "CVE-2026-109619",
                "namespace": "nvd:cpe",
                "severity": "High",
                "fix": {
                    "versions": ["8.2.35", "8.3.36", "8.4.27", "8.5.12"],
                    "state": "fixed",
                },
            },
            "relatedVulnerabilities": [],
            "artifact": {"name": "php-cli", "version": "8.4.26", "type": "binary"},
        },
    ]
}

CYCLONEDX = {
    "bomFormat": "CycloneDX",
    "components": [
        {
            "type": "library",
            "name": "lodash",
            "version": "4.17.15",
            "purl": "pkg:npm/lodash@4.17.15",
        },
        {
            "type": "library",
            "name": "libssl3",
            "version": "3.0.2-0ubuntu1",
            "purl": "pkg:deb/ubuntu/libssl3@3.0.2-0ubuntu1?arch=amd64&distro=ubuntu-22.04&upstream=openssl",
        },
        {
            "type": "library",
            "name": "libc6",
            "version": "2.36-9+deb12u4",
            "purl": "pkg:deb/debian/libc6@2.36-9+deb12u4?arch=amd64&upstream=glibc%402.36-9%2Bdeb12u4&distro=debian-12",
        },
        {
            "type": "library",
            "name": "zlib",
            "version": "1.3.2-r0",
            "purl": "pkg:apk/alpine/zlib@1.3.2-r0?arch=x86_64&distro=alpine-3.24.2",
        },
        {"type": "operating-system", "name": "ubuntu", "version": "22.04"},
    ],
}


SEVERITY = {"CRITICAL": "fail", "HIGH": "warn"}
STRICT = {"CRITICAL": "fail", "HIGH": "fail"}


def _config(**overrides):
    raw = {
        "targets": ["host", "container"],
        "engines": ["trivy", "grype", "osv", "syft"],
        "severity": SEVERITY,
        "fixed_only": True,
        "workers": 2,
        "db_update": True,
    }
    raw.update(overrides)
    return SCRIPT.scan_config(raw)


def _finding(**fields):
    defaults = {
        "engine": "trivy",
        "target": "host",
        "package": "openssl",
        "installed": "1.0",
        "fixed": "1.1",
        "ids": ("CVE-2026-0001",),
        "severity": "HIGH",
    }
    defaults.update(fields)
    return SCRIPT.Finding(**defaults)


def _suppressions(containers=None, host=None):
    return SCRIPT.Suppressions(containers=containers or {}, host=host or {})


def _rule(cve="CVE-2026-0001", until=TODAY):
    return SCRIPT.Suppression(id=cve, until=until)


def _container(name, stack=None, service=None, image="sha256:img"):
    return SCRIPT.Container(
        id=f"id-{name}",
        name=name,
        stack=stack,
        service=service,
        image=image,
        image_name=f"{name}:1",
    )


def _legacy_floor_violation(version, floors):
    current = tuple(
        int(part) for part in re.match(r"^(\d+)\.(\d+)\.(\d+)", version).groups()
    )
    line = f"{current[0]}.{current[1]}"
    if line in floors:
        floor = tuple(int(part) for part in floors[line].split("."))
        return f"below {floors[line]}" if current < floor else None
    newest = max(tuple(int(part) for part in key.split(".")) for key in floors)
    return (
        None if current[:2] > newest else f"{version} runs the end-of-life line {line}"
    )


class TestNegativeControl(TestCase):
    def test_the_removed_floor_flagged_the_patched_jammy_build(self):
        floors = {"8.2": "8.2.35", "8.3": "8.3.36", "8.4": "8.4.27", "8.5": "8.5.12"}
        self.assertEqual(
            _legacy_floor_violation(JAMMY_PHP, floors),
            f"{JAMMY_PHP} runs the end-of-life line 8.1",
        )

    def test_every_engine_passes_the_patched_jammy_build(self):
        findings = (
            [
                f
                for f in SCRIPT.parse_trivy(TRIVY_HOST, "host")
                if f.package.startswith("php")
            ]
            + [
                f
                for f in SCRIPT.parse_grype(GRYPE_HOST, "host")
                if f.package.startswith("php")
            ]
            + [
                f
                for f in SCRIPT.parse_osv(OSV_HOST, lambda _path: "host")
                if f.package.startswith("php")
            ]
        )
        self.assertEqual(len(findings), 3)
        failures, warnings, _infos = SCRIPT.evaluate(
            findings,
            {"host": SCRIPT.host_target("node")},
            _config(),
            _suppressions(),
            TODAY,
        )
        self.assertEqual((failures, warnings), ([], []))

    def test_a_fixable_critical_fails(self):
        findings = [
            f for f in SCRIPT.parse_trivy(TRIVY_HOST, "host") if f.package == "minimist"
        ]
        failures, _warnings, _infos = SCRIPT.evaluate(
            findings,
            {"host": SCRIPT.host_target("node")},
            _config(),
            _suppressions(),
            TODAY,
        )
        self.assertEqual(
            failures,
            [
                "trivy host node: CVE-2021-44906 CRITICAL minimist 1.2.0 (fixed in 1.2.6, 0.2.4)"
            ],
        )


class TestSourceBuiltRuntime(TestCase):
    def test_runtime_sbom_keeps_only_binary_packages(self):
        reduced = SCRIPT.runtime_sbom(SYFT_PHP_IMAGE)
        self.assertEqual([a["name"] for a in reduced["artifacts"]], ["php-cli"])

    def test_runtime_sbom_drops_files_and_relationships(self):
        reduced = SCRIPT.runtime_sbom(SYFT_PHP_IMAGE)
        self.assertEqual(
            (reduced["artifactRelationships"], "files" in reduced), ([], False)
        )

    def test_runtime_sbom_keeps_the_distro(self):
        self.assertEqual(
            SCRIPT.runtime_sbom(SYFT_PHP_IMAGE)["distro"], SYFT_PHP_IMAGE["distro"]
        )

    def test_an_sbom_without_binaries_needs_no_runtime_pass(self):
        sbom = {**SYFT_PHP_IMAGE, "artifacts": SYFT_PHP_IMAGE["artifacts"][:1]}
        self.assertIsNone(SCRIPT.runtime_sbom(sbom))

    def _php_runtime(self):
        target = SCRIPT.Target(
            "img",
            "container",
            "sha256:img",
            "roundcube:1.7.5-apache",
            (("roundcube", "roundcube"),),
        )
        return SCRIPT.evaluate(
            SCRIPT.parse_grype(GRYPE_PHP_RUNTIME, "img"),
            {"img": target},
            _config(),
            _suppressions(),
            TODAY,
        )

    def test_source_built_php_8_4_26_fails_on_its_critical(self):
        failures, _warnings, _infos = self._php_runtime()
        self.assertEqual(len(failures), 1)
        self.assertIn("CVE-2026-109618 CRITICAL php-cli 8.4.26", failures[0])
        self.assertIn("8.4.27", failures[0])

    def test_source_built_php_8_4_26_warns_on_its_high(self):
        _failures, warnings, _infos = self._php_runtime()
        self.assertEqual(len(warnings), 1)
        self.assertIn("CVE-2026-109619 HIGH php-cli 8.4.26", warnings[0])

    def test_trivy_and_osv_without_grype_still_run_the_runtime_pass(self):
        for engine in ("trivy", "osv"):
            with self.subTest(engine=engine):
                self.assertTrue(_config(engines=["syft", engine]).runtime_pass())

    def test_a_pinned_engine_reads_the_grype_database_too(self):
        self.assertEqual(
            _config(engines=["syft", "trivy"]).databases(), ("trivy", "grype")
        )

    def test_grype_in_the_list_needs_no_extra_pass(self):
        self.assertFalse(_config(engines=["syft", "grype"]).runtime_pass())


class TestScanConfig(TestCase):
    def test_the_role_default_is_valid(self):
        config = _config()
        self.assertEqual(config.scanners(), ("trivy", "grype", "osv"))

    def test_an_unknown_engine_is_rejected(self):
        with self.assertRaisesRegex(SCRIPT.ConfigError, "unknown engines: clair"):
            _config(engines=["clair"])

    def test_syft_alone_names_no_scanner(self):
        with self.assertRaisesRegex(SCRIPT.ConfigError, "no scanner"):
            _config(engines=["syft"])

    def test_osv_without_syft_cannot_scan_the_host(self):
        with self.assertRaisesRegex(SCRIPT.ConfigError, "osv reads no OS packages"):
            _config(engines=["osv", "grype"])

    def test_osv_without_syft_may_scan_containers(self):
        self.assertFalse(
            _config(engines=["osv", "grype"], targets=["container"]).reads_sbom("osv")
        )

    def test_trivy_without_syft_or_grype_misses_source_built_runtimes(self):
        with self.assertRaisesRegex(SCRIPT.ConfigError, "source-built runtimes"):
            _config(engines=["trivy"])

    def test_a_missing_key_is_rejected(self):
        raw = {
            "targets": ["host"],
            "engines": ["grype"],
            "severity": {"HIGH": "fail"},
            "fixed_only": True,
            "workers": 1,
        }
        with self.assertRaisesRegex(SCRIPT.ConfigError, "db_update"):
            SCRIPT.scan_config(raw)

    def test_the_severity_mapping_is_kept_in_severity_order(self):
        config = _config(severity={"HIGH": "warn", "CRITICAL": "fail"})
        self.assertEqual(
            list(config.severity.items()), [("CRITICAL", "fail"), ("HIGH", "warn")]
        )

    def test_the_retired_list_form_is_rejected(self):
        with self.assertRaisesRegex(SCRIPT.ConfigError, "list form"):
            _config(severity=["CRITICAL", "HIGH"])

    def test_an_unknown_action_is_rejected(self):
        with self.assertRaisesRegex(SCRIPT.ConfigError, "HIGH: ignore"):
            _config(severity={"CRITICAL": "fail", "HIGH": "ignore"})

    def test_an_unknown_severity_is_rejected(self):
        with self.assertRaisesRegex(SCRIPT.ConfigError, "unknown severity: SEVERE"):
            _config(severity={"SEVERE": "fail"})

    def test_an_empty_mapping_is_rejected(self):
        with self.assertRaisesRegex(SCRIPT.ConfigError, "non-empty mapping"):
            _config(severity={})

    def test_a_string_bool_is_rejected(self):
        with self.assertRaisesRegex(SCRIPT.ConfigError, "fixed_only"):
            _config(fixed_only="True")

    def test_zero_workers_are_rejected(self):
        with self.assertRaisesRegex(SCRIPT.ConfigError, "workers"):
            _config(workers=0)


class TestParsers(TestCase):
    def test_trivy_reads_package_versions_and_severity(self):
        finding = SCRIPT.parse_trivy(TRIVY_HOST, "host")[0]
        self.assertEqual(
            (
                finding.package,
                finding.installed,
                finding.fixed,
                finding.severity,
                finding.id,
            ),
            ("libssl3", "3.0.2-0ubuntu1", "3.0.2-0ubuntu1.7", "HIGH", "CVE-2022-3602"),
        )

    def test_trivy_without_a_fixed_version_has_no_fix(self):
        self.assertEqual(SCRIPT.parse_trivy(TRIVY_HOST, "host")[1].fixed, "")

    def test_trivy_vendor_ids_become_aliases(self):
        finding = SCRIPT.parse_trivy(TRIVY_HOST, "host")[2]
        self.assertEqual(finding.ids, ("CVE-2021-44906", "GHSA-xvch-5gv4-984h"))

    def test_trivy_without_results_reports_nothing(self):
        self.assertEqual(SCRIPT.parse_trivy({"SchemaVersion": 2}, "host"), [])

    def test_grype_prefers_the_related_cve_id(self):
        finding = SCRIPT.parse_grype(GRYPE_HOST, "host")[1]
        self.assertEqual(
            (finding.id, finding.ids),
            ("CVE-2020-8203", ("CVE-2020-8203", "GHSA-p6mc-m468-83gw")),
        )

    def test_grype_severity_is_upper_case(self):
        self.assertEqual(SCRIPT.parse_grype(GRYPE_HOST, "host")[0].severity, "HIGH")

    def test_grype_not_fixed_has_no_fix(self):
        self.assertEqual(SCRIPT.parse_grype(GRYPE_HOST, "host")[2].fixed, "")

    def test_osv_maps_the_group_cvss_to_a_severity(self):
        severities = [
            f.severity for f in SCRIPT.parse_osv(OSV_HOST, lambda _path: "host")
        ]
        self.assertEqual(severities, ["HIGH", "CRITICAL", "HIGH"])

    def test_osv_takes_fixed_from_the_ranges_of_the_same_package(self):
        lodash = SCRIPT.parse_osv(OSV_HOST, lambda _path: "host")[0]
        self.assertEqual(lodash.fixed, "4.17.19")

    def test_osv_without_a_fixed_event_has_no_fix(self):
        php = SCRIPT.parse_osv(OSV_HOST, lambda _path: "host")[2]
        self.assertEqual(php.fixed, "")

    def test_osv_collects_upstream_and_group_aliases(self):
        openssl = SCRIPT.parse_osv(OSV_HOST, lambda _path: "host")[1]
        self.assertEqual(openssl.ids[0], "CVE-2022-1292")
        self.assertIn("USN-5402-1", openssl.ids)

    def test_osv_maps_each_source_to_its_target(self):
        seen = []
        SCRIPT.parse_osv(OSV_HOST, lambda path: seen.append(path) or "host")
        self.assertEqual(seen, [OSV_SOURCE])


class TestCvssSeverity(TestCase):
    def test_boundaries(self):
        cases = {
            "9.0": "CRITICAL",
            "8.9": "HIGH",
            "7.0": "HIGH",
            "6.9": "MEDIUM",
            "4.0": "MEDIUM",
            "0.1": "LOW",
            "0.0": "NONE",
            "": "UNKNOWN",
        }
        for score, severity in cases.items():
            with self.subTest(score=score):
                self.assertEqual(SCRIPT.cvss_severity(score), severity)


class TestOsvSbom(TestCase):
    def _purls(self):
        return [c.get("purl") for c in SCRIPT.osv_sbom(CYCLONEDX)["components"]]

    def test_a_deb_purl_names_the_source_package(self):
        self.assertTrue(
            self._purls()[1].startswith("pkg:deb/ubuntu/openssl@3.0.2-0ubuntu1?")
        )

    def test_a_source_version_replaces_the_binary_version(self):
        self.assertTrue(
            self._purls()[2].startswith("pkg:deb/debian/glibc@2.36-9+deb12u4?")
        )

    def test_a_purl_without_upstream_is_kept(self):
        self.assertEqual(self._purls()[3], CYCLONEDX["components"][3]["purl"])

    def test_a_language_purl_is_kept(self):
        self.assertEqual(self._purls()[0], "pkg:npm/lodash@4.17.15")

    def test_the_input_is_not_changed(self):
        SCRIPT.osv_sbom(CYCLONEDX)
        self.assertIn("libssl3@", CYCLONEDX["components"][1]["purl"])


class TestThreshold(TestCase):
    def test_a_fixable_critical_maps_to_fail(self):
        self.assertEqual(
            SCRIPT.threshold(_finding(severity="CRITICAL"), _config()), "fail"
        )

    def test_a_fixable_high_maps_to_warn(self):
        self.assertEqual(SCRIPT.threshold(_finding(), _config()), "warn")

    def test_an_unfixed_critical_is_below_the_threshold_while_fixed_only(self):
        self.assertIsNone(
            SCRIPT.threshold(_finding(severity="CRITICAL", fixed=""), _config())
        )

    def test_an_unfixed_critical_fails_without_fixed_only(self):
        self.assertEqual(
            SCRIPT.threshold(
                _finding(severity="CRITICAL", fixed=""), _config(fixed_only=False)
            ),
            "fail",
        )

    def test_an_unmapped_severity_is_below_the_threshold(self):
        self.assertIsNone(SCRIPT.threshold(_finding(severity="MEDIUM"), _config()))


class TestVerdict(TestCase):
    def _verdict(self, suppressed, action):
        return SCRIPT.Verdict(
            _finding(),
            SCRIPT.host_target("node"),
            (None, None),
            _rule() if suppressed else None,
            suppressed,
            action,
        )

    def test_an_unsuppressed_verdict_is_its_action(self):
        self.assertEqual(
            [self._verdict(False, action).verdict for action in SCRIPT.ACTIONS],
            ["fail", "warn"],
        )

    def test_a_suppressed_verdict_is_suppressed_whatever_its_action(self):
        self.assertEqual(
            {self._verdict(True, action).verdict for action in SCRIPT.ACTIONS},
            {"suppressed"},
        )


class TestSuppressions(TestCase):
    def _container_target(self, owners):
        return SCRIPT.Target(
            "img", "container", "sha256:img", "checkmk/check-mk-raw:2.4.0p39", owners
        )

    def _evaluate(self, target, suppressions, finding=None):
        return SCRIPT.evaluate(
            [finding or _finding(target=target.key)],
            {target.key: target},
            _config(severity=STRICT),
            suppressions,
            TODAY,
        )

    def test_a_suppression_of_the_owning_role_silences_its_container(self):
        target = self._container_target((("checkmk", "checkmk"),))
        failures, _warnings, infos = self._evaluate(
            target, _suppressions({"checkmk": {"checkmk": (_rule(),)}})
        )
        self.assertEqual((failures, len(infos)), ([], 1))

    def test_a_suppression_of_another_role_does_not_apply(self):
        target = self._container_target((("checkmk", "checkmk"),))
        failures, _warnings, _infos = self._evaluate(
            target, _suppressions({"nextcloud": {"checkmk": (_rule(),)}})
        )
        self.assertEqual(len(failures), 1)

    def test_a_suppression_of_another_service_of_the_role_does_not_apply(self):
        target = self._container_target((("checkmk", "checkmk"),))
        failures, _warnings, _infos = self._evaluate(
            target, _suppressions({"checkmk": {"checkmkmcp": (_rule(),)}})
        )
        self.assertEqual(len(failures), 1)

    def test_a_shared_image_fails_for_the_owner_without_suppression(self):
        target = self._container_target((("checkmk", "checkmk"), ("other", "app")))
        failures, _warnings, _infos = self._evaluate(
            target, _suppressions({"checkmk": {"checkmk": (_rule(),)}})
        )
        self.assertEqual(
            failures,
            [
                "trivy container other/app checkmk/check-mk-raw:2.4.0p39: CVE-2026-0001 HIGH openssl 1.0 (fixed in 1.1)"
            ],
        )

    def test_an_expired_suppression_fails_and_says_so(self):
        target = self._container_target((("checkmk", "checkmk"),))
        failures, _warnings, infos = self._evaluate(
            target,
            _suppressions(
                {"checkmk": {"checkmk": (_rule(until=TODAY - dt.timedelta(days=1)),)}}
            ),
        )
        self.assertEqual(len(failures), 1)
        self.assertIn("expired on 2026-10-30", infos[0])

    def test_a_suppression_matches_an_alias(self):
        target = self._container_target((("checkmk", "checkmk"),))
        finding = _finding(target="img", ids=("CVE-2026-0002", "GHSA-aaaa-bbbb-cccc"))
        failures, _warnings, _infos = self._evaluate(
            target,
            _suppressions({"checkmk": {"checkmk": (_rule("CVE-2026-0002"),)}}),
            finding,
        )
        self.assertEqual(failures, [])

    def test_a_host_suppression_covers_only_its_engine(self):
        target = SCRIPT.host_target("node")
        suppressions = _suppressions(host={"grype": (_rule(),)})
        failures, _warnings, _infos = SCRIPT.evaluate(
            [_finding(engine="trivy"), _finding(engine="grype")],
            {"host": target},
            _config(severity=STRICT),
            suppressions,
            TODAY,
        )
        self.assertEqual(
            failures, ["trivy host node: CVE-2026-0001 HIGH openssl 1.0 (fixed in 1.1)"]
        )

    def test_an_unmanaged_container_cannot_be_suppressed(self):
        target = self._container_target(((None, None),))
        failures, _warnings, _infos = self._evaluate(target, _suppressions())
        self.assertIn("unmanaged container", failures[0])

    def test_suppressions_from_json(self):
        parsed = SCRIPT.suppressions_from_json(
            {
                "containers": {
                    "checkmk": {
                        "checkmk": [{"id": "CVE-2026-1", "until": "2026-12-31"}]
                    }
                },
                "host": {},
            }
        )
        self.assertEqual(
            parsed.containers["checkmk"]["checkmk"][0].until,
            dt.date(2026, 12, 31),
        )


class TestContainerTargets(TestCase):
    def test_containers_of_one_image_share_a_target(self):
        targets = SCRIPT.container_targets(
            [
                _container("a", "checkmk", "checkmk"),
                _container("b", "checkmk", "checkmk"),
            ]
        )
        self.assertEqual(len(targets), 1)
        self.assertEqual(
            targets[0].owners, (("checkmk", "checkmk"), ("checkmk", "checkmk"))
        )

    def test_the_target_key_is_the_image_digest(self):
        target = SCRIPT.container_targets([_container("a", image="sha256:abc")])[0]
        self.assertEqual(target.key, "abc")


EMPTY_REPORTS = {
    "trivy.json": {"SchemaVersion": 2},
    "grype.json": {"matches": []},
    "runtime.grype.json": {"matches": []},
    "json": {"results": []},
}


class FakeEngines:
    """A runner that answers every engine command with a fixture report."""

    def __init__(self, layout, reports, *, fail=()):
        self.layout = layout
        self.reports = {**EMPTY_REPORTS, **reports}
        self.fail = fail
        self.calls = []
        self.active = 0
        self.peak = 0
        self.lock = threading.Lock()

    def __call__(self, argv):
        with self.lock:
            self.calls.append(list(argv))
            self.active += 1
            self.peak = max(self.peak, self.active)
        try:
            text = " ".join(argv)
            for marker in self.fail:
                if marker in text:
                    return SimpleNamespace(returncode=2, stdout="", stderr="boom")
            self._write(list(argv))
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        finally:
            with self.lock:
                self.active -= 1

    def _write(self, argv):
        for index, arg in enumerate(argv):
            if arg in ("--output", "--file", "--output-file"):
                name = Path(argv[index + 1]).name
                report = self.reports[name.split(".", 1)[1]]
                (self.layout.work / name).write_text(
                    json.dumps(report), encoding="utf-8"
                )
            if arg.startswith(("syft-json=", "cyclonedx-json=")):
                name = Path(arg.split("=", 1)[1]).name
                document = SYFT_PHP_IMAGE if name.endswith("syft.json") else CYCLONEDX
                (self.layout.sbom / name).write_text(
                    json.dumps(document), encoding="utf-8"
                )


class TestScan(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        for name in ("db", "sbom", "work"):
            (root / name).mkdir()
        self.layout = SCRIPT.Layout(
            runtime=("container", "run"),
            databases=root / "db",
            sbom=root / "sbom",
            work=root / "work",
            excludes=("/proc",),
        )
        self.images = {engine: f"{engine}:1" for engine in SCRIPT.ENGINES}
        self.targets = [SCRIPT.host_target("node")]

    def tearDown(self):
        self.tmp.cleanup()

    def _scan(self, config, reports, fail=()):
        runner = FakeEngines(self.layout, reports, fail=fail)
        with mock.patch.object(SCRIPT, "pause") as self.pauses:
            findings, errors = SCRIPT.scan(
                self.targets, config, self.images, self.layout, runner
            )
        return findings, errors, runner

    def _download_calls(self, runner, flag):
        return [call for call in runner.calls if flag in call]

    def test_a_failing_database_download_is_retried_with_a_short_pause(self):
        _findings, _errors, runner = self._scan(
            _config(targets=["host"]), {}, fail=("--download-db-only",)
        )
        self.assertEqual(
            len(self._download_calls(runner, "--download-db-only")), SCRIPT.DB_ATTEMPTS
        )
        self.assertEqual(
            [call.args for call in self.pauses.call_args_list],
            [(SCRIPT.DB_RETRY_SECONDS,)] * (SCRIPT.DB_ATTEMPTS - 1),
        )

    def test_a_database_download_that_recovers_is_not_retried_again(self):
        attempts = []

        def flaky(argv):
            if "--download-db-only" in argv:
                attempts.append(argv)
                if len(attempts) == 1:
                    return SimpleNamespace(returncode=1, stdout="", stderr="timeout")
            return FakeEngines(self.layout, {})(argv)

        with mock.patch.object(SCRIPT, "pause"):
            _findings, errors = SCRIPT.scan(
                self.targets, _config(targets=["host"]), self.images, self.layout, flaky
            )
        self.assertEqual((len(attempts), errors), (2, []))

    def test_a_finding_is_never_retried(self):
        _findings, _errors, runner = self._scan(
            _config(targets=["host"]), {"trivy.json": TRIVY_HOST}
        )
        self.assertEqual(len(self._download_calls(runner, "rootfs")), 1)
        self.pauses.assert_not_called()

    def test_every_engine_reports_into_one_result(self):
        reports = {"trivy.json": TRIVY_HOST, "grype.json": GRYPE_HOST, "json": OSV_HOST}
        findings, errors, _runner = self._scan(_config(targets=["host"]), reports)
        self.assertEqual(errors, [])
        self.assertEqual({f.engine for f in findings}, {"trivy", "grype", "osv"})

    def test_the_parallel_runs_respect_the_worker_bound(self):
        _findings, _errors, runner = self._scan(
            _config(targets=["host"], workers=1), {}
        )
        self.assertEqual(runner.peak, 1)

    def test_a_failing_database_download_fails_loudly_and_skips_the_engine(self):
        findings, errors, runner = self._scan(
            _config(targets=["host"]),
            {"trivy.json": TRIVY_HOST},
            fail=("--download-db-only",),
        )
        self.assertTrue(
            any(error.startswith("trivy database: exited 2") for error in errors)
        )
        self.assertFalse(any("rootfs" in call for call in runner.calls))
        self.assertNotIn("trivy", {f.engine for f in findings})

    def test_a_provided_database_that_is_missing_fails_loudly(self):
        _findings, errors, runner = self._scan(
            _config(targets=["host"], engines=["syft", "grype"], db_update=False), {}
        )
        self.assertEqual(
            errors,
            [
                f"grype: provided database {self.layout.databases / 'grype' / '6/vulnerability.db'} is missing"
            ],
        )
        self.assertFalse(
            any("db" in call and "update" in call for call in runner.calls)
        )

    def test_a_pinned_trivy_run_still_scans_source_built_runtimes_with_grype(self):
        for engine in ("trivy", "grype"):
            for marker in SCRIPT.DB_MARKERS[engine]:
                path = self.layout.databases / engine / marker
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("", encoding="utf-8")
        findings, errors, _runner = self._scan(
            _config(targets=["host"], engines=["syft", "trivy"], db_update=False),
            {"runtime.grype.json": GRYPE_PHP_RUNTIME},
        )
        self.assertEqual(errors, [])
        self.assertEqual(
            {(f.engine, f.id) for f in findings},
            {("grype", "CVE-2026-109618"), ("grype", "CVE-2026-109619")},
        )

    def test_the_provided_trivy_database_is_read_from_memory_cache(self):
        step = SCRIPT.trivy_step(
            self.layout,
            "trivy:1",
            self.targets[0],
            _config(db_update=False, engines=["syft", "trivy"]),
        )
        self.assertIn("memory", step.argv)

    def test_a_failed_sbom_skips_the_sbom_readers_of_that_target(self):
        _findings, errors, runner = self._scan(
            _config(targets=["host"], engines=["syft", "grype"]),
            {},
            fail=("dir:/host",),
        )
        self.assertTrue(errors[0].startswith("syft host node: exited 2"))
        self.assertFalse(
            any(arg.startswith("sbom:") for call in runner.calls for arg in call)
        )

    def test_osv_names_a_missing_ecosystem_database(self):
        result = SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="could not load db for PyPI ecosystem: no offline",
        )
        errors = SCRIPT.run_lane(
            [SCRIPT.Step("osv sbom", ("x",), SCRIPT.OSV_ACCEPTED_EXIT_CODES)],
            lambda _argv: result,
        )
        self.assertEqual(errors, ["osv sbom: no OSV database for PyPI"])

    def test_osv_exit_code_one_means_findings(self):
        result = SimpleNamespace(returncode=1, stdout="", stderr="")
        errors = SCRIPT.run_lane(
            [SCRIPT.Step("osv sbom", ("x",), SCRIPT.OSV_ACCEPTED_EXIT_CODES)],
            lambda _argv: result,
        )
        self.assertEqual(errors, [])

    def test_a_timed_out_engine_is_an_error(self):
        def hung(_argv):
            raise subprocess.TimeoutExpired(cmd="trivy", timeout=5)

        errors = SCRIPT.run_lane(
            [SCRIPT.Step("trivy host node", ("x",), SCRIPT.SUCCESS)], hung
        )
        self.assertEqual(errors, ["trivy host node: no result within 5s"])


class TestCommands(TestCase):
    def setUp(self):
        self.layout = SCRIPT.Layout(
            runtime=("container", "run"),
            databases=Path("/var/cache/v/db"),
            sbom=Path("/var/cache/v/sbom"),
            work=Path("/var/cache/v/run"),
            excludes=("/proc", "/var/lib/docker"),
        )
        self.host = SCRIPT.host_target("node")
        self.container = SCRIPT.Target(
            "abc", "container", "sha256:abc", "app:1", (("app", "app"),)
        )

    def test_the_host_is_mounted_read_only(self):
        step = SCRIPT.trivy_step(self.layout, "trivy:1", self.host, _config())
        self.assertIn("/:/host:ro", step.argv)

    def test_every_engine_writes_its_temp_files_to_the_work_mount(self):
        for engine in ("trivy", "grype", "osv", "syft"):
            with self.subTest(engine=engine):
                argv = SCRIPT.run_argv(
                    self.layout, engine, f"{engine}:1", [], target=None, extra_env={}
                )
                self.assertIn("TMPDIR=/work", argv)
                self.assertIn("/var/cache/v/run:/work", argv)

    def test_the_grype_database_update_writes_its_listing_to_the_work_mount(self):
        (step,) = SCRIPT.db_steps("grype", self.layout, "grype:1")
        self.assertIn("TMPDIR=/work", step.argv)

    def test_a_container_scan_reads_the_docker_socket_read_only(self):
        step = SCRIPT.trivy_step(self.layout, "trivy:1", self.container, _config())
        self.assertIn("/var/run/docker.sock:/var/run/docker.sock:ro", step.argv)

    def test_the_host_scan_skips_the_excluded_paths(self):
        step = SCRIPT.trivy_step(self.layout, "trivy:1", self.host, _config())
        self.assertIn("/host/proc,/host/var/lib/docker", step.argv)

    def test_syft_scans_the_host_with_the_image_catalogers(self):
        step = SCRIPT.sbom_step(self.layout, "syft:1", self.host)
        self.assertIn("--override-default-catalogers", step.argv)
        self.assertIn("./var/lib/docker", step.argv)

    def test_grype_reads_the_sbom_when_syft_runs(self):
        step = SCRIPT.grype_step(self.layout, "grype:1", self.container, _config())
        self.assertIn("sbom:/sbom/abc.syft.json", step.argv)

    def test_grype_reads_the_image_without_syft(self):
        step = SCRIPT.grype_step(
            self.layout,
            "grype:1",
            self.container,
            _config(engines=["grype"], targets=["container"]),
        )
        self.assertIn("docker:sha256:abc", step.argv)

    def test_osv_without_syft_exports_the_image(self):
        steps = SCRIPT.osv_image_steps(
            self.layout,
            "osv:1",
            self.container,
            _config(engines=["osv", "grype"], targets=["container"]),
        )
        self.assertEqual(steps[0].argv[:2], ("container", "save"))

    def test_osv_downloads_its_databases_only_when_asked(self):
        self.assertIn(
            "--download-offline-databases", SCRIPT.osv_args(_config(), "/work/osv.json")
        )
        self.assertNotIn(
            "--download-offline-databases",
            SCRIPT.osv_args(
                _config(db_update=False, engines=["syft", "osv"]), "/work/osv.json"
            ),
        )


class TestParseProbe(TestCase):
    def test_startup_warnings_before_the_probe_line_are_skipped(self):
        stdout = f"PHP Warning:  Module 'redis' already loaded\n{MARKER}||0\n"
        self.assertEqual(
            SCRIPT.parse_probe(stdout).settings,
            {"expose_php": False, "session.upload_progress.enabled": False},
        )

    def test_enabled_settings_are_reported_on(self):
        self.assertEqual(
            SCRIPT.parse_probe(f"\n{MARKER}|1|1\n").settings,
            {"expose_php": True, "session.upload_progress.enabled": True},
        )

    def test_output_without_the_probe_line_raises(self):
        with self.assertRaises(SCRIPT.ProbeError):
            SCRIPT.parse_probe("Segmentation fault\n")

    def test_a_probe_line_with_missing_fields_raises(self):
        with self.assertRaises(SCRIPT.ProbeError):
            SCRIPT.parse_probe(f"{MARKER}|1\n")


class TestIdentity(TestCase):
    def test_compose_labels_give_project_and_service(self):
        labels = {
            "com.docker.compose.project": "nextcloud",
            "com.docker.compose.service": "cron",
        }
        self.assertEqual(SCRIPT.identity(labels), ("nextcloud", "cron"))

    def test_swarm_labels_strip_the_stack_prefix(self):
        labels = {
            "com.docker.stack.namespace": "nextcloud",
            "com.docker.swarm.service.name": "nextcloud_nextcloud",
        }
        self.assertEqual(SCRIPT.identity(labels), ("nextcloud", "nextcloud"))

    def test_a_container_without_labels_has_no_identity(self):
        self.assertEqual(SCRIPT.identity(None), (None, None))


def _probe(expose_php=False, upload_progress=False):
    return SCRIPT.PhpProbe(
        settings={
            "expose_php": expose_php,
            "session.upload_progress.enabled": upload_progress,
        }
    )


def _check(containers, probes, hardened):
    return SCRIPT.check(containers, hardened, lambda container_id: probes[container_id])


class TestCheck(TestCase):
    def test_a_hardened_service_with_expose_php_on_fails(self):
        failures, _infos = _check(
            [_container("wp", "wordpress", "wordpress")],
            {"id-wp": _probe(expose_php=True)},
            {"wordpress": ["wordpress"]},
        )
        self.assertEqual(
            failures, ["wp: expose_php on, the php_hardening ini is not in effect"]
        )

    def test_a_hardened_service_with_both_settings_off_passes(self):
        self.assertEqual(
            _check(
                [_container("wp", "wordpress", "wordpress")],
                {"id-wp": _probe()},
                {"wordpress": ["wordpress"]},
            ),
            ([], []),
        )

    def test_a_sidecar_of_a_hardened_stack_is_info_only(self):
        failures, infos = _check(
            [_container("nc-cron", "nextcloud", "cron")],
            {"id-nc-cron": _probe(upload_progress=True)},
            {"nextcloud": ["nextcloud"]},
        )
        self.assertEqual(failures, [])
        self.assertEqual(
            infos,
            [
                "nc-cron: session.upload_progress.enabled on (sidecar without php_hardening)"
            ],
        )

    def test_a_container_outside_hardened_stacks_is_not_probed(self):
        self.assertEqual(
            _check(
                [_container("app", "other", "app")], {}, {"wordpress": ["wordpress"]}
            ),
            ([], []),
        )

    def test_a_hardened_service_without_php_fails(self):
        failures, _infos = _check(
            [_container("wp", "wordpress", "wordpress")],
            {"id-wp": None},
            {"wordpress": ["wordpress"]},
        )
        self.assertEqual(
            failures, ["wp: declares php_hardening but has no php to verify it"]
        )

    def test_a_probe_error_in_a_hardened_stack_is_a_failure(self):
        def broken(_container_id):
            raise SCRIPT.ProbeError("php exited 255: boom")

        failures, _infos = SCRIPT.check(
            [_container("wp", "wordpress", "wordpress")],
            {"wordpress": ["wordpress"]},
            broken,
        )
        self.assertEqual(failures, ["wp: php exited 255: boom"])


class TestProbePhp(TestCase):
    def _run(self, returncode, stdout="", stderr=""):
        completed = SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)
        with mock.patch.object(SCRIPT.subprocess, "run", return_value=completed):
            return SCRIPT.probe_php("abc")

    def test_exit_127_means_no_php(self):
        self.assertIsNone(self._run(127, stderr="executable file not found"))

    def test_another_non_zero_exit_raises(self):
        with self.assertRaises(SCRIPT.ProbeError):
            self._run(255, stderr="PHP Fatal error")

    def test_a_timeout_raises(self):
        with (
            mock.patch.object(
                SCRIPT.subprocess,
                "run",
                side_effect=subprocess.TimeoutExpired(cmd="php", timeout=60),
            ),
            self.assertRaises(SCRIPT.ProbeError),
        ):
            SCRIPT.probe_php("abc")


class TestRunningContainers(TestCase):
    def test_the_image_of_every_container_is_read(self):
        def fake_run(args, **_kwargs):
            if args[:2] == ["container", "ps"]:
                return SimpleNamespace(returncode=0, stdout="id-app\n", stderr="")
            inspected = [
                {
                    "Id": "id-app",
                    "Name": "/app",
                    "Image": "sha256:abc",
                    "Config": {"Labels": None, "Image": "app:1"},
                }
            ]
            return SimpleNamespace(
                returncode=0, stdout=json.dumps(inspected), stderr=""
            )

        with mock.patch.object(SCRIPT.subprocess, "run", side_effect=fake_run):
            container = SCRIPT.running_containers()[0]
        self.assertEqual(
            (container.image, container.image_name), ("sha256:abc", "app:1")
        )


RUN = SCRIPT.Run(
    id="run-1",
    started=dt.datetime(2026, 10, 31, 0, 0, 5, tzinfo=dt.UTC),
    host="node",
    environment="production",
)
NEXTCLOUD = SCRIPT.Target(
    "abc",
    "container",
    "sha256:abc",
    "nextcloud:31",
    (("nextcloud", "nextcloud"), ("nextcloud", "cron")),
)


def _verdict(target, owner, *, action, rule=None, **fields):
    return SCRIPT.Verdict(
        _finding(target=target.key, **fields),
        target,
        owner,
        rule,
        rule is not None,
        action,
    )


def _outcome(verdicts, *, errors=(), failed=False, targets=()):
    return SCRIPT.Outcome(
        run=RUN,
        targets=tuple(targets),
        records=tuple(SCRIPT.record(verdict, RUN) for verdict in verdicts),
        errors=tuple(errors),
        engines=("grype", "syft"),
        failed=failed,
        finished=1793404805.5,
    )


class TestRecord(TestCase):
    def test_a_container_record_names_owner_image_and_suppression(self):
        verdict = _verdict(
            NEXTCLOUD,
            ("nextcloud", "nextcloud"),
            action="warn",
            rule=_rule(until=dt.date(2026, 12, 31)),
            engine="osv",
        )
        self.assertEqual(
            SCRIPT.record(verdict, RUN),
            {
                "run_id": "run-1",
                "timestamp": "2026-10-31T00:00:05Z",
                "host": "node",
                "environment": "production",
                "target": "nextcloud/nextcloud",
                "kind": "container",
                "image": "nextcloud:31@sha256:abc",
                "scanner": "osv",
                "id": "CVE-2026-0001",
                "severity": "HIGH",
                "package": "openssl",
                "installed_version": "1.0",
                "fixed_version": "1.1",
                "suppressed": True,
                "suppressed_until": "2026-12-31",
                "verdict": "suppressed",
            },
        )

    def test_a_host_record_names_the_host_as_target_and_image(self):
        record = SCRIPT.record(
            _verdict(SCRIPT.host_target("node"), (None, None), action="fail"), RUN
        )
        self.assertEqual(
            (record["target"], record["image"], record["kind"]),
            ("node", "node", "host"),
        )

    def test_an_unsuppressed_record_carries_its_action_and_no_until(self):
        record = SCRIPT.record(
            _verdict(SCRIPT.host_target("node"), (None, None), action="fail"), RUN
        )
        self.assertEqual(
            (record["verdict"], record["suppressed"], record["suppressed_until"]),
            ("fail", False, None),
        )

    def test_a_finding_without_a_fix_has_no_fixed_version(self):
        record = SCRIPT.record(
            _verdict(SCRIPT.host_target("node"), (None, None), action="fail", fixed=""),
            RUN,
        )
        self.assertIsNone(record["fixed_version"])


class TestJournalEvents(TestCase):
    def test_each_owner_of_a_shared_image_gets_its_own_line(self):
        outcome = _outcome(
            [_verdict(NEXTCLOUD, ("nextcloud", "nextcloud"), action="fail")],
            targets=[NEXTCLOUD],
        )
        self.assertEqual(
            [
                (event["target"], event["counts"], event["verdict"])
                for event in outcome.target_events()
            ],
            [
                ("nextcloud/cron", {"fail": 0, "warn": 0, "suppressed": 0}, "ok"),
                (
                    "nextcloud/nextcloud",
                    {"fail": 1, "warn": 0, "suppressed": 0},
                    "fail",
                ),
            ],
        )

    def test_a_target_with_warnings_only_is_warn(self):
        host = SCRIPT.host_target("node")
        outcome = _outcome(
            [
                _verdict(host, (None, None), action="warn"),
                _verdict(host, (None, None), action="fail", rule=_rule()),
            ],
            targets=[host],
        )
        self.assertEqual(
            outcome.target_events()[0]["counts"],
            {"fail": 0, "warn": 1, "suppressed": 1},
        )
        self.assertEqual(outcome.target_events()[0]["verdict"], "warn")

    def test_an_engine_error_fails_the_summary_without_findings(self):
        summary = _outcome(
            [], errors=["grype database: exited 1"], failed=True
        ).summary_event()
        self.assertEqual(
            summary,
            {
                "event": "hlth_runtime.summary",
                "run_id": "run-1",
                "counts": {"fail": 0, "warn": 0, "suppressed": 0},
                "errors": 1,
                "verdict": "fail",
            },
        )


class TestMetrics(TestCase):
    def _lines(self, outcome):
        return outcome.metrics().splitlines()

    def test_one_series_counts_the_findings_of_one_label_set(self):
        host = SCRIPT.host_target("node")
        lines = self._lines(
            _outcome(
                [
                    _verdict(host, (None, None), action="fail", severity="CRITICAL"),
                    _verdict(
                        host,
                        (None, None),
                        action="fail",
                        severity="CRITICAL",
                        ids=("CVE-2026-0002",),
                    ),
                ]
            )
        )
        self.assertIn(
            'infinito_hlth_runtime_findings{target="node",kind="host",image="node",'
            'severity="CRITICAL",scanner="trivy",verdict="fail"} 2',
            lines,
        )

    def test_no_series_names_the_vulnerability(self):
        text = _outcome(
            [_verdict(NEXTCLOUD, ("nextcloud", "nextcloud"), action="warn")]
        ).metrics()
        labels = re.findall(r"(\w+)=\"", text.split("_findings{", 1)[1].split("}")[0])
        self.assertEqual((tuple(labels), "CVE-" in text), (SCRIPT.METRIC_LABELS, False))

    def test_every_metric_declares_help_and_gauge_type(self):
        lines = self._lines(_outcome([]))
        for name in (
            "findings",
            "last_run_timestamp_seconds",
            "last_run_success",
            "scanner_errors",
        ):
            with self.subTest(metric=name):
                metric = f"infinito_hlth_runtime_{name}"
                self.assertTrue(
                    any(line.startswith(f"# HELP {metric} ") for line in lines)
                )
                self.assertIn(f"# TYPE {metric} gauge", lines)

    def test_the_last_run_carries_its_time_and_success(self):
        lines = self._lines(_outcome([], failed=True))
        self.assertIn(
            "infinito_hlth_runtime_last_run_timestamp_seconds 1793404805", lines
        )
        self.assertIn("infinito_hlth_runtime_last_run_success 0", lines)

    def test_scanner_errors_are_counted_per_engine_with_clean_engines_at_zero(self):
        lines = self._lines(
            _outcome(
                [],
                errors=[
                    "grype database: exited 1",
                    "grype: provided database /db/grype/6/vulnerability.db is missing",
                    "osv export app:1: exited 1",
                ],
            )
        )
        self.assertEqual(
            [
                line
                for line in lines
                if line.startswith("infinito_hlth_runtime_scanner")
            ],
            [
                'infinito_hlth_runtime_scanner_errors{scanner="grype"} 2',
                'infinito_hlth_runtime_scanner_errors{scanner="osv"} 1',
                'infinito_hlth_runtime_scanner_errors{scanner="syft"} 0',
            ],
        )

    def test_label_values_are_escaped(self):
        target = SCRIPT.Target(
            "abc", "container", "sha256:abc", 'odd"\\name\n', ((None, None),)
        )
        text = _outcome([_verdict(target, (None, None), action="warn")]).metrics()
        self.assertIn('image="odd\\"\\\\name\\n@sha256:abc"', text)


class TestWriteAtomic(TestCase):
    def test_the_file_is_replaced_without_a_leftover_temp_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "infinito_hlth_runtime.prom"
            SCRIPT.write_atomic(path, "old\n")
            SCRIPT.write_atomic(path, "new\n")
            text = path.read_text()  # nocheck: cache-read tempdir file rewritten
            self.assertEqual(
                ([p.name for p in Path(tmp).iterdir()], text),
                (["infinito_hlth_runtime.prom"], "new\n"),
            )


NO_SUPPRESSIONS = {"containers": {}, "host": {}}
MAIN_SCAN = {
    "targets": ["host"],
    "engines": ["grype"],
    "severity": SEVERITY,
    "fixed_only": True,
    "workers": 1,
    "db_update": True,
}
CRITICAL_FINDING = _finding(engine="grype", severity="CRITICAL")
HIGH_FINDING = _finding(engine="grype", ids=("CVE-2026-0002",))


class TestMain(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for name in ("cache", "report", "log", "metrics"):
            (self.root / name).mkdir()
        self.metrics = self.root / "metrics" / "infinito_hlth_runtime.prom"

    def tearDown(self):
        self.tmp.cleanup()

    def _args(self, scan, suppressions, metrics):
        return [
            "--scan",
            json.dumps(scan),
            "--hardened",
            "{}",
            "--images",
            "{}",
            "--suppressions",
            json.dumps(suppressions),
            "--cache-dir",
            str(self.root / "cache"),
            "--database-dir",
            str(self.root / "cache" / "db"),
            "--host-excludes",
            "[]",
            "--environment",
            "production",
            "--report-dir",
            str(self.root / "report"),
            "--log-dir",
            str(self.root / "log"),
            *metrics,
        ]

    def _early(self, scan, side_effect):
        with (
            mock.patch.object(SCRIPT.subprocess, "run", side_effect=side_effect),
            contextlib.redirect_stdout(io.StringIO()) as out,
        ):
            code = SCRIPT.main(self._args(scan, NO_SUPPRESSIONS, []))
        return code, out.getvalue()

    def _main(self, findings, *, errors=(), suppressions=NO_SUPPRESSIONS, metrics=None):
        flags = ["--metrics-file", str(self.metrics)] if metrics is None else metrics
        with (
            mock.patch.object(SCRIPT, "running_containers", return_value=[]),
            mock.patch.object(SCRIPT, "check", return_value=([], [])),
            mock.patch.object(SCRIPT, "docker_root", return_value="/var/lib/docker"),
            mock.patch.object(
                SCRIPT, "scan", return_value=(list(findings), list(errors))
            ),
            mock.patch.object(SCRIPT.socket, "gethostname", return_value="node"),
            contextlib.redirect_stdout(io.StringIO()) as out,
        ):
            code = SCRIPT.main(self._args(MAIN_SCAN, suppressions, flags))
        return code, out.getvalue()

    def _report(self):
        path = self.root / "report" / "report.json"
        text = path.read_text()  # nocheck: cache-read tempdir report of main()
        return json.loads(text)

    def test_an_invalid_scan_config_fails_with_one_line(self):
        code, output = self._early(
            {"targets": ["host"]}, AssertionError("no engine call expected")
        )
        self.assertEqual((code, len(output.splitlines())), (1, 1))
        self.assertIn("scan config lacks", output)

    def test_a_hung_container_listing_fails_with_one_line(self):
        code, output = self._early(
            MAIN_SCAN, subprocess.TimeoutExpired(cmd=["container", "ps"], timeout=60)
        )
        self.assertEqual((code, len(output.splitlines())), (1, 1))
        self.assertIn("timed out after 60 seconds", output)

    def test_a_finding_mapped_to_fail_fails_the_run(self):
        code, output = self._main([CRITICAL_FINDING])
        self.assertEqual(code, 1)
        self.assertIn(
            "❌ grype host node: CVE-2026-0001 CRITICAL openssl 1.0 (fixed in 1.1)",
            output,
        )

    def test_a_finding_mapped_to_warn_passes_with_a_warning(self):
        code, output = self._main([HIGH_FINDING])
        self.assertEqual((code, "❌" in output), (0, False))
        self.assertIn(
            "⚠️ grype host node: CVE-2026-0002 HIGH openssl 1.0 (fixed in 1.1)", output
        )

    def test_a_suppressed_finding_is_info_and_passes(self):
        suppressions = {
            "containers": {},
            "host": {"grype": [{"id": "CVE-2026-0001", "until": "2099-12-31"}]},
        }
        code, output = self._main([CRITICAL_FINDING], suppressions=suppressions)
        self.assertEqual(code, 0)
        self.assertIn(
            "ℹ️ grype host node: CVE-2026-0001 CRITICAL openssl 1.0 (fixed in 1.1) "
            "suppressed until 2099-12-31",
            output,
        )

    def test_an_engine_error_still_fails_the_check(self):
        code, output = self._main([], errors=["grype database: exited 1"])
        self.assertEqual(code, 1)
        self.assertIn("❌ grype database: exited 1", output)

    def test_the_journal_has_one_json_line_per_target(self):
        _code, output = self._main([CRITICAL_FINDING, HIGH_FINDING])
        events = [json.loads(line) for line in output.splitlines() if line[:1] == "{"]
        target = events[0]
        self.assertEqual(
            (len(events), target["event"], target["target"], target["kind"]),
            (2, "hlth_runtime.target", "node", "host"),
        )
        self.assertEqual(
            (target["counts"], target["verdict"]),
            ({"fail": 1, "warn": 1, "suppressed": 0}, "fail"),
        )

    def test_the_journal_ends_with_the_summary(self):
        _code, output = self._main([HIGH_FINDING])
        summary = json.loads(output.splitlines()[-1])
        self.assertEqual(
            {key: summary[key] for key in ("event", "counts", "errors", "verdict")},
            {
                "event": "hlth_runtime.summary",
                "counts": {"fail": 0, "warn": 1, "suppressed": 0},
                "errors": 0,
                "verdict": "warn",
            },
        )

    def test_the_report_holds_the_summary_and_the_records(self):
        self._main(
            [CRITICAL_FINDING, HIGH_FINDING], errors=["grype database: exited 1"]
        )
        report = self._report()
        self.assertEqual(
            (
                report["host"],
                report["environment"],
                report["verdict"],
                report["counts"],
                report["errors"],
                [(item["id"], item["verdict"]) for item in report["findings"]],
            ),
            (
                "node",
                "production",
                "fail",
                {"fail": 1, "warn": 1, "suppressed": 0},
                ["grype database: exited 1"],
                [("CVE-2026-0001", "fail"), ("CVE-2026-0002", "warn")],
            ),
        )

    def test_the_report_holds_the_last_run_only(self):
        self._main([CRITICAL_FINDING])
        self._main([])
        self.assertEqual(
            (self._report()["findings"], self._report()["verdict"]), ([], "ok")
        )

    def test_findings_are_appended_across_runs(self):
        self._main([CRITICAL_FINDING])
        self._main([HIGH_FINDING])
        path = self.root / "log" / "findings.jsonl"
        text = path.read_text()  # nocheck: cache-read tempdir log of two runs
        records = [json.loads(line) for line in text.splitlines()]
        self.assertEqual(
            [item["id"] for item in records], ["CVE-2026-0001", "CVE-2026-0002"]
        )
        self.assertNotEqual(records[0]["run_id"], records[1]["run_id"])

    def test_the_metrics_file_is_written_when_asked(self):
        self._main([CRITICAL_FINDING])
        text = self.metrics.read_text()  # nocheck: cache-read tempdir metrics of main()
        self.assertIn(
            'infinito_hlth_runtime_findings{target="node",kind="host",image="node",'
            'severity="CRITICAL",scanner="grype",verdict="fail"} 1',
            text.splitlines(),
        )

    def test_no_metrics_file_is_written_without_the_flag(self):
        self._main([CRITICAL_FINDING], metrics=[])
        written = list(self.root.rglob("*.prom"))  # nocheck: project-walk tempdir
        self.assertEqual(written, [])

    def test_no_metrics_file_is_written_for_an_empty_flag(self):
        self._main([CRITICAL_FINDING], metrics=["--metrics-file", ""])
        written = list(self.root.rglob("*.prom"))  # nocheck: project-walk tempdir
        self.assertEqual(written, [])


if __name__ == "__main__":
    main()
