from __future__ import annotations

import datetime as dt
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase, main, mock

import cli.contributing.security.scan.__main__ as scan_main
from utils.docker.image.discovery import ImageRef
from utils.security.pipeline import pipeline

P = pipeline()


def _ref(role, service, name="library/php", version="8.4.26-cli"):
    return ImageRef(
        role=role,
        service=service,
        name=name,
        version=version,
        source=f"docker.io/{name}:{version}",
        registry="docker.io",
    )


class TestResolveDigests(TestCase):
    def _resolve(self, refs, digests):
        with mock.patch.object(
            scan_main,
            "mirror_image",
            side_effect=lambda image: f"ghcr.io/o/r/mirror/{image}",
        ):
            return scan_main.resolve_digests(
                refs, lambda image, tag: digests.get(f"{image}:{tag}"), 2
            )

    def test_role_services_pinning_one_digest_share_a_target(self):
        refs = [_ref("web-app-a", "a"), _ref("web-app-b", "b")]
        grouped, sources, errors = self._resolve(
            refs, {"ghcr.io/o/r/mirror/docker.io/library/php:8.4.26-cli": "sha256:abc"}
        )
        self.assertEqual(
            (list(grouped), [len(v) for v in grouped.values()], errors),
            (["sha256:abc"], [2], []),
        )
        self.assertEqual(
            sources["sha256:abc"], "ghcr.io/o/r/mirror/docker.io/library/php"
        )

    def test_an_image_the_mirror_does_not_serve_is_an_error(self):
        _grouped, _sources, errors = self._resolve([_ref("web-app-a", "a")], {})
        self.assertIn("the mirror served no digest", errors[0])

    def test_an_unresolvable_mirror_aborts(self):
        with (
            mock.patch.object(scan_main, "mirror_image", return_value=None),
            self.assertRaises(SystemExit),
        ):
            scan_main.resolve_digests(
                [_ref("web-app-a", "a")], lambda image, tag: None, 1
            )


class TestTargets(TestCase):
    def test_every_owning_role_service_is_an_owner(self):
        target = scan_main.targets_of(
            P, {"sha256:abc": [_ref("web-app-b", "b"), _ref("web-app-a", "a")]}
        )[0]
        self.assertEqual(target.owners, (("web-app-a", "a"), ("web-app-b", "b")))
        self.assertEqual(target.key, "abc")

    def test_each_owner_keeps_its_own_pinned_tag(self):
        target = scan_main.targets_of(
            P,
            {
                "sha256:abc": [
                    _ref("web-app-moodle", "nginx", "library/nginx", "1.31.8-alpine"),
                    _ref("web-app-hugo", "nginx", "library/nginx", "1.31-alpine"),
                ]
            },
        )[0]
        self.assertEqual(
            (
                target.tag_of(("web-app-hugo", "nginx")),
                target.tag_of(("web-app-moodle", "nginx")),
            ),
            ("1.31-alpine", "1.31.8-alpine"),
        )


class TestSteps(TestCase):
    def setUp(self):
        self.layout = P.Layout(
            runtime=("docker", "run"),
            databases=Path("/c/db"),
            sbom=Path("/c/sbom"),
            work=Path("/c/run"),
            excludes=(),
        )
        self.target = P.Target(
            "abc",
            "container",
            "sha256:abc",
            "docker.io/library/php:8.4.26-cli",
            (("r", "s"),),
            ((("r", "s"), "8.4.26-cli"),),
        )

    def test_syft_reads_the_mirror_by_digest_without_a_daemon(self):
        step = scan_main.sbom_step(
            P, self.layout, self.target, "ghcr.io/o/r/mirror/docker.io/library/php"
        )
        self.assertIn(
            "registry:ghcr.io/o/r/mirror/docker.io/library/php@sha256:abc", step.argv
        )
        self.assertNotIn("/var/run/docker.sock:/var/run/docker.sock:ro", step.argv)

    def test_trivy_reads_the_sbom_tree(self):
        step = scan_main.trivy_step(P, self.layout, self.target)
        self.assertEqual(step.argv[step.argv.index("sbom") :][-1], "/sbom/abc.cdx.json")


MIRROR_SOURCES = {"sha256:abc": "ghcr.io/o/r/mirror/docker.io/library/php"}


class TestReport(TestCase):
    target = P.Target(
        "abc",
        "container",
        "sha256:abc",
        "docker.io/library/php:8.4.26-cli",
        (("r", "s"),),
        ((("r", "s"), "8.4.26-cli"),),
    )

    def _finding(self, severity):
        return P.Finding(
            "grype",
            "abc",
            "php-cli",
            "8.4.26",
            "8.4.27",
            ("CVE-2026-109618",),
            severity,
        )

    def test_a_suppressed_verdict_is_reported_with_its_until_but_does_not_fail(self):
        finding = self._finding("CRITICAL")
        verdicts = [
            P.Verdict(finding, self.target, ("r", "s"), None, False, "fail"),
            P.Verdict(
                finding,
                self.target,
                ("r", "t"),
                P.Suppression(None, "8.4.26-cli", dt.date(2026, 12, 3)),
                True,
                "fail",
            ),
        ]
        rows = scan_main.report_rows(verdicts, MIRROR_SOURCES)
        self.assertEqual(
            (
                [(row["service"], row["suppressed_until"]) for row in rows],
                [row["service"] for row in scan_main.failing(rows)],
            ),
            ([("s", None), ("t", "2026-12-03")], ["s"]),
        )

    def test_only_unsuppressed_verdicts_fail(self):
        finding = self._finding("CRITICAL")
        verdicts = [
            P.Verdict(finding, self.target, ("r", "s"), None, False, "fail"),
            P.Verdict(
                finding,
                self.target,
                ("r", "t"),
                P.Suppression("CVE-2026-109618", None, dt.date(2026, 12, 31)),
                True,
                "fail",
            ),
        ]
        rows = scan_main.report_rows(verdicts, MIRROR_SOURCES)
        self.assertEqual(
            [
                (row["role"], row["service"], row["id"])
                for row in scan_main.failing(rows)
            ],
            [("r", "s", "CVE-2026-109618")],
        )

    def test_a_finding_the_role_only_warns_on_is_still_reported(self):
        verdict = P.Verdict(
            self._finding("HIGH"), self.target, ("r", "s"), None, False, "warn"
        )
        rows = scan_main.report_rows([verdict], MIRROR_SOURCES)
        self.assertEqual([row["severity"] for row in rows], ["HIGH"])

    def test_the_role_mapping_is_a_valid_mirror_scan_config(self):
        config = scan_main.scan_config(P, 1)
        self.assertLessEqual(set(config.severity.values()), set(P.ACTIONS))


class TestExitCode(TestCase):
    def _run(self, errors):
        finding = P.Finding(
            "grype",
            "abc",
            "php-cli",
            "8.4.26",
            "8.4.27",
            ("CVE-2026-109618",),
            "CRITICAL",
        )
        p = mock.MagicMock()
        p.verdicts.return_value = [
            P.Verdict(finding, TestReport.target, ("r", "s"), None, False, "fail")
        ]
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.object(scan_main, "pipeline", return_value=p),
            mock.patch.object(
                scan_main, "scan_config", return_value=SimpleNamespace(workers=1)
            ),
            mock.patch.object(scan_main, "iter_role_images", return_value=[]),
            mock.patch.object(
                scan_main,
                "resolve_digests",
                return_value=({}, MIRROR_SOURCES, list(errors)),
            ),
            mock.patch.object(scan_main, "targets_of", return_value=[]),
            mock.patch.object(scan_main, "user_runtime", return_value=("docker",)),
            mock.patch.object(scan_main, "scan_tree", return_value=([], [])),
            mock.patch.object(scan_main, "suppressions_of", return_value={}),
            mock.patch("builtins.print"),
        ):
            return scan_main.main(
                [
                    "--cache-dir",
                    f"{tmp}/cache",
                    "--report",
                    f"{tmp}/report.json",
                    "--workers",
                    "1",
                ]
            )

    def test_an_unsuppressed_finding_alone_passes(self):
        self.assertEqual(self._run([]), 0)

    def test_an_engine_error_fails(self):
        self.assertEqual(self._run(["trivy img: exited 1"]), 1)


class TestScanTree(TestCase):
    def test_a_cached_sbom_is_not_rebuilt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("db", "sbom", "run"):
                (root / name).mkdir()
            layout = P.Layout(
                runtime=("docker", "run"),
                databases=root / "db",
                sbom=root / "sbom",
                work=root / "run",
                excludes=(),
            )
            target = P.Target(
                "abc",
                "container",
                "sha256:abc",
                "img",
                (("r", "s"),),
                ((("r", "s"), "latest"),),
            )
            (root / "sbom" / "abc.syft.json").write_text("{}", encoding="utf-8")
            (root / "sbom" / "abc.cdx.json").write_text(
                json.dumps({"components": []}), encoding="utf-8"
            )
            calls = []

            def runner(argv):
                calls.append(list(argv))
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            config = scan_main.scan_config(P, 1)
            scan_main.scan_tree(
                P, [target], {"sha256:abc": "m"}, config, layout, runner
            )
        self.assertFalse(
            any(any(arg.startswith("registry:") for arg in call) for call in calls)
        )


if __name__ == "__main__":
    main()
