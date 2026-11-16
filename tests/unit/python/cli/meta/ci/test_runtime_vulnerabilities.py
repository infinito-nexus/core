from __future__ import annotations

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

import cli.contributing.security.issues.__main__ as issues_main
from cli.meta.ci import runtime_vulnerabilities as rv
from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml
from utils.security.pipeline import pipeline

P = pipeline()
PREFIX = "mirror"
TODAY = dt.date(2026, 11, 12)
UNTIL = dt.date(2026, 12, 31)
NGINX = "ghcr.io/infinito-nexus/core/mirror/docker.io/nginx:1.31-alpine"
CADVISOR = "ghcr.io/infinito-nexus/core/mirror/ghcr.io/google/cadvisor:v0.60.6"
LOCAL = "openresty_custom:1.31.8.1-alpine"
CLEAN = "ghcr.io/infinito-nexus/core/mirror/docker.io/library/redis:8.4-alpine"
OWNER = ("openresty", "openresty")
PROMETHEUS = ("prometheus", "cadvisor")
NGINX_TITLE = "🛡️ docker.io/library/nginx:1.31-alpine"
CADVISOR_TITLE = "🛡️ ghcr.io/google/cadvisor:v0.60.6"
LOCAL_TITLE = f"🛡️ {LOCAL}"
CLEAN_TITLE = "🛡️ docker.io/library/redis:8.4-alpine"
HOST_TITLE = "🛡️ host debian"
PREFIX_LINE = "Nov 12 05:10:34 node hlth-runtime.17.0.0.infinito.nexus[42]: "
MARKS = ("❌", "⚠️", "ℹ️")
CI_LINE = (
    "❌ grype container prometheus/blackbox-exporter "
    "ghcr.io/infinito-nexus/core/mirror/docker.io/prom/blackbox-exporter:v0.29.1: "
    "CVE-2026-111497 CRITICAL github.com/andybalholm/brotli v1.2.6 (fixed in 1.2.7)"
)
ENGINE_ERROR = "❌ osv sbom: no OSV database for Wolfi"


def target(key, label, owner):
    return P.Target(
        key=key,
        kind="container",
        ref=f"sha256:{key}",
        label=label,
        owners=(owner,),
        owner_tags=((owner, P.image_tag(label)),),
    )


def finding(key, cve, severity, fixed, package="zlib"):
    return P.Finding(
        engine="grype",
        target=key,
        package=package,
        installed="1.3.2-r1",
        fixed=fixed,
        ids=(cve,),
        severity=severity,
    )


def journal(engine_errors=0):
    nginx = target("n", NGINX, OWNER)
    cadvisor = target("c", CADVISOR, PROMETHEUS)
    local = target("l", LOCAL, OWNER)
    clean = target("r", CLEAN, ("baserow", "redis"))
    host = P.host_target("node")
    tag = P.Suppression(id=None, image_tag="v0.60.6", until=UNTIL)
    judged = [
        P.Verdict(
            finding("n", "CVE-2026-4738", "CRITICAL", "1.4-r0"),
            nginx,
            OWNER,
            None,
            False,
            "warn",
        ),
        P.Verdict(
            finding("n", "CVE-2026-0001", "HIGH", ""), nginx, OWNER, None, False, "warn"
        ),
        P.Verdict(
            finding("c", "CVE-2026-0002", "CRITICAL", "1.4-r0"),
            cadvisor,
            PROMETHEUS,
            tag,
            True,
            "warn",
        ),
        P.Verdict(
            finding("c", "CVE-2026-0003", "HIGH", ""),
            cadvisor,
            PROMETHEUS,
            tag,
            True,
            "warn",
        ),
        P.Verdict(
            finding("l", "CVE-2026-0004", "CRITICAL", "2.0"),
            local,
            OWNER,
            None,
            False,
            "fail",
        ),
        P.Verdict(
            finding("host", "CVE-2025-22871", "CRITICAL", "1.24.2", "stdlib"),
            host,
            (None, None),
            None,
            False,
            "warn",
        ),
    ]
    failures, warnings, infos = P.report_lines(judged)
    run = P.Run(
        id="r",
        started=dt.datetime(2026, 11, 12, tzinfo=dt.UTC),
        host="node",
        environment="development",
    )
    outcome = P.Outcome(
        run=run,
        targets=(nginx, cadvisor, local, clean, host),
        records=tuple(P.record(verdict, run) for verdict in judged),
        errors=tuple(f"osv: broken {index}" for index in range(engine_errors)),
        engines=("grype",),
        failed=bool(failures),
        finished=0.0,
    )
    lines = [
        *(f"{MARKS[2]} {line}" for line in infos),
        *(f"{MARKS[1]} {line}" for line in warnings),
        *(f"{MARKS[0]} {line}" for line in failures),
        CI_LINE,
        ENGINE_ERROR,
        *(
            json.dumps(event)
            for event in [*outcome.target_events(), outcome.summary_event()]
        ),
    ]
    return "".join(f"{PREFIX_LINE}{line}\n" for line in lines)


def write_bundle(
    root, name="rescue-diagnostics-compose-svc-x-0-debian-ext4-amd64", engine_errors=0
):
    text = journal(engine_errors)
    base = Path(root) / name / "debian" / "svc-x"
    for relative in (
        "svc-x-20261112051034Z-1/journal.txt",
        "ci-host/svc-x-20261112051203Z-2/containers/infinito_nexus_debian.journal.txt",
    ):
        path = base / relative
        path.parent.mkdir(parents=True)
        path.write_text(text, encoding="utf-8")


def collected(engine_errors=0):
    with tempfile.TemporaryDirectory() as root:
        write_bundle(root, engine_errors=engine_errors)
        return rv.collect(Path(root), PREFIX)


def rows_of(report, title):
    return [row for row in report["findings"] if issues_main.title(row) == title]


class FakeGh:
    def __init__(self, issues=(), bundle=None):
        self.issues = list(issues)
        self.bundle = bundle
        self.calls = []

    def __call__(self, args):
        args = list(args)
        self.calls.append(args)
        if args[:2] == ["run", "download"]:
            self.bundle(args[args.index("-D") + 1])
        if args[:2] == ["issue", "list"]:
            label = args[args.index("--label") + 1]
            return json.dumps(
                [issue for issue in self.issues if label in issue["labels"]]
            )
        return ""

    def writes(self):
        return [call for call in self.calls if call[0] == "issue" and call[1] != "list"]

    def touched(self, number):
        return [call for call in self.writes() if call[2] == str(number)]


class TestParse(unittest.TestCase):
    def test_a_mirror_finding_becomes_a_row_with_every_column(self):
        rows = rows_of(collected(), NGINX_TITLE)
        critical = next(row for row in rows if row["severity"] == "CRITICAL")
        self.assertEqual(
            {key: critical[key] for key in issues_main.COLUMNS},
            {
                "id": "CVE-2026-4738",
                "severity": "CRITICAL",
                "engine": "grype",
                "role": "svc-prx-openresty",
                "service": "openresty",
                "package": "zlib",
                "installed": "1.3.2-r1",
                "fixed": "1.4-r0",
                "suppressed_until": None,
            },
        )

    def test_a_real_ci_line_parses_and_an_engine_error_line_does_not(self):
        report = collected()
        self.assertEqual(
            [
                row["package"]
                for row in rows_of(report, "🛡️ docker.io/prom/blackbox-exporter:v0.29.1")
            ],
            ["github.com/andybalholm/brotli"],
        )
        self.assertFalse(
            [row for row in report["findings"] if "Wolfi" in json.dumps(row)]
        )

    def test_the_two_journals_of_one_bundle_yield_each_finding_once(self):
        self.assertEqual(len(rows_of(collected(), NGINX_TITLE)), 2)

    def test_an_image_tag_suppression_fills_every_row_it_covers(self):
        report = collected()
        covered = rows_of(report, CADVISOR_TITLE)
        self.assertEqual(
            [row["suppressed_until"] for row in covered], ["2026-12-31"] * 2
        )
        uncovered = rows_of(report, NGINX_TITLE)
        self.assertEqual({row["suppressed_until"] for row in uncovered}, {None})

    def test_a_local_build_keeps_its_name_and_the_host_one_title_per_distro(self):
        report = collected()
        self.assertEqual(len(rows_of(report, LOCAL_TITLE)), 1)
        host = rows_of(report, HOST_TITLE)
        self.assertEqual(
            [(row["role"], row["service"]) for row in host], [(rv.ROLE, "grype")]
        )


class TestBody(unittest.TestCase):
    def _cells(self, text, cve):
        line = next(line for line in text.splitlines() if line.startswith(f"| {cve} "))
        return dict(
            zip(
                issues_main.COLUMNS,
                (cell.strip() for cell in line.strip("|").split("|")),
                strict=True,
            )
        )

    def test_the_head_line_counts_each_severity(self):
        text = issues_main.body(rows_of(collected(), NGINX_TITLE), rv.RUNTIME)
        self.assertTrue(text.splitlines()[0].endswith(": CRITICAL 1, HIGH 1."), text)
        self.assertIn(
            "Runtime: `ghcr.io/infinito-nexus/core/mirror/docker.io/nginx:1.31-alpine`",
            text,
        )

    def test_fixed_is_a_dash_without_a_fix_and_the_version_with_one(self):
        text = issues_main.body(rows_of(collected(), NGINX_TITLE), rv.RUNTIME)
        self.assertEqual(self._cells(text, "CVE-2026-0001")["fixed"], "-")
        self.assertEqual(self._cells(text, "CVE-2026-4738")["fixed"], "1.4-r0")

    def test_a_suppressed_row_shows_its_day_and_an_open_one_a_dash(self):
        report = collected()
        suppressed = issues_main.body(rows_of(report, CADVISOR_TITLE), rv.RUNTIME)
        self.assertEqual(
            self._cells(suppressed, "CVE-2026-0003")["suppressed_until"], "2026-12-31"
        )
        open_body = issues_main.body(rows_of(report, NGINX_TITLE), rv.RUNTIME)
        self.assertEqual(
            self._cells(open_body, "CVE-2026-0001")["suppressed_until"], "-"
        )


class TestLabels(unittest.TestCase):
    def mirror_issue(self):
        return {
            "number": 1,
            "title": NGINX_TITLE,
            "body": "mirror table",
            "labels": [issues_main.LABEL],
        }

    def test_a_runtime_sync_never_touches_a_mirror_issue(self):
        gh = FakeGh(
            [
                self.mirror_issue(),
                {**self.mirror_issue(), "number": 2, "title": CLEAN_TITLE},
            ]
        )
        actions = issues_main.sync(collected(), "o/r", gh, rv.RUNTIME)
        self.assertEqual((gh.touched(1), gh.touched(2)), ([], []))
        labels = {
            call[call.index("--label") + 1] for call in gh.calls if "--label" in call
        }
        self.assertEqual(labels, {rv.RUNTIME.label})
        self.assertIn(f"opened {NGINX_TITLE}", actions)

    def test_negative_control_the_mirror_sync_does_close_its_own_issue(self):
        gh = FakeGh([self.mirror_issue()])
        issues_main.sync({"findings": [], "errors": []}, "o/r", gh, issues_main.MIRROR)
        self.assertEqual([call[1] for call in gh.touched(1)], ["close"])

    def test_a_mirror_sync_never_touches_a_runtime_issue(self):
        runtime = {
            "number": 3,
            "title": NGINX_TITLE,
            "body": "x",
            "labels": [rv.RUNTIME.label],
        }
        gh = FakeGh([runtime])
        issues_main.sync({"findings": [], "errors": []}, "o/r", gh, issues_main.MIRROR)
        self.assertEqual(gh.touched(3), [])


class TestClose(unittest.TestCase):
    def issue(self, number, title):
        return {
            "number": number,
            "title": title,
            "body": "old",
            "labels": [rv.RUNTIME.label],
        }

    def test_a_scanned_image_without_findings_closes_its_issue(self):
        gh = FakeGh([self.issue(5, CLEAN_TITLE)])
        actions = issues_main.sync(collected(), "o/r", gh, rv.RUNTIME)
        self.assertIn(f"closed #5 {CLEAN_TITLE}", actions)
        close = gh.touched(5)[0]
        self.assertEqual(close[close.index("--comment") + 1], rv.RUNTIME.gone)

    def test_negative_control_an_image_this_run_did_not_scan_stays_open(self):
        title = "🛡️ docker.io/library/postgres:16-alpine"
        gh = FakeGh([self.issue(6, title)])
        issues_main.sync(collected(), "o/r", gh, rv.RUNTIME)
        self.assertEqual(gh.touched(6), [])

    def test_negative_control_a_scan_with_engine_errors_closes_nothing(self):
        report = collected(engine_errors=1)
        gh = FakeGh([self.issue(5, CLEAN_TITLE)])
        issues_main.sync(report, "o/r", gh, rv.RUNTIME)
        self.assertEqual((gh.touched(5), report["scanned"]), ([], []))
        self.assertTrue(report["errors"])


class TestMainGuard(unittest.TestCase):
    def run_report(self, ref):
        gh = FakeGh(bundle=write_bundle)
        with tempfile.TemporaryDirectory() as dest:
            actions = rv.report(
                run_id="9", repo="o/r", ref=ref, dest=Path(dest), prefix=PREFIX, gh=gh
            )
        return gh, actions

    def test_a_pull_request_run_files_nothing(self):
        gh, actions = self.run_report("refs/pull/7/merge")
        self.assertEqual(gh.calls, [])
        self.assertTrue(actions[0].startswith("skipped: refs/pull/7/merge"))

    def test_negative_control_a_main_run_downloads_and_files(self):
        gh, actions = self.run_report(rv.MAIN_REF)
        self.assertEqual(gh.calls[0][:2], ["run", "download"])
        self.assertIn(f"opened {NGINX_TITLE}", actions)

    def guarded(self, job):
        step = next(
            step
            for step in job["steps"]
            if "runtime_vulnerabilities" in step.get("run", "")
        )
        return (
            "github.ref == 'refs/heads/main'" in job["if"]
            and '--ref "${GITHUB_REF}"' in step["run"]
        )

    def test_the_workflow_job_runs_only_on_main_and_hands_the_ref_on(self):
        workflow = PROJECT_ROOT / ".github" / "workflows" / "call-orchestrator.yml"
        job = load_yaml(str(workflow))["jobs"]["report-main-failures"]
        self.assertTrue(self.guarded(job))
        self.assertFalse(self.guarded({**job, "if": "${{ always() }}"}))


if __name__ == "__main__":
    unittest.main()
