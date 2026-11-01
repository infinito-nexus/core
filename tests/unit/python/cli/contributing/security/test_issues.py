from __future__ import annotations

import json
import subprocess
from unittest import TestCase, main

import cli.contributing.security.issues.__main__ as issues_main

ROW = {
    "engine": "grype",
    "role": "web-app-roundcube",
    "service": "roundcube",
    "image": "docker.io/roundcube/roundcubemail:1.7.5-apache",
    "mirror": "ghcr.io/o/r/mirror/docker.io/roundcube/roundcubemail",
    "digest": "sha256:abc",
    "id": "CVE-2026-109618",
    "ids": ["CVE-2026-109618"],
    "severity": "CRITICAL",
    "package": "php-cli",
    "installed": "8.4.26",
    "fixed": "8.4.27",
}
TITLE = "🛡️ CVE-2026-109618 in docker.io/roundcube/roundcubemail:1.7.5-apache"


class FakeGh:
    def __init__(self, open_issues, hang=()):
        self.open_issues = open_issues
        self.hang = [list(verb) for verb in hang]
        self.calls = []

    def __call__(self, args):
        if list(args[:2]) in self.hang:
            raise subprocess.TimeoutExpired(["gh", *args], 120)
        self.calls.append(list(args))
        if args[:2] == ["issue", "list"]:
            return json.dumps(self.open_issues)
        return ""

    def verbs(self):
        return [
            call[:2] for call in self.calls if call[0] == "issue" and call[1] != "list"
        ]


class TestSync(TestCase):
    def test_a_new_finding_opens_one_issue(self):
        gh = FakeGh([])
        issues_main.sync(
            {"findings": [ROW, {**ROW, "engine": "trivy"}], "errors": []}, "o/r", gh
        )
        self.assertEqual(gh.verbs(), [["issue", "create"]])

    def test_a_known_finding_updates_its_issue(self):
        gh = FakeGh([{"number": 7, "title": TITLE}])
        issues_main.sync({"findings": [ROW], "errors": []}, "o/r", gh)
        self.assertEqual(gh.calls[-1][:3], ["issue", "edit", "7"])

    def test_a_fixed_finding_closes_its_issue(self):
        gh = FakeGh([{"number": 7, "title": TITLE}])
        actions = issues_main.sync({"findings": [], "errors": []}, "o/r", gh)
        self.assertEqual(actions, [f"closed #7 {TITLE}"])

    def test_a_scan_error_closes_nothing(self):
        gh = FakeGh([{"number": 7, "title": TITLE}])
        issues_main.sync(
            {"findings": [], "errors": ["x: the mirror served no digest"]}, "o/r", gh
        )
        self.assertEqual(gh.verbs(), [])

    def test_a_failed_issue_call_is_reported_and_the_others_still_run(self):
        other = {**ROW, "id": "CVE-2026-109619"}
        gh = FakeGh([{"number": 7, "title": TITLE}], hang=[("issue", "edit")])
        actions = issues_main.sync({"findings": [ROW, other], "errors": []}, "o/r", gh)
        self.assertTrue(actions[0].startswith(f"failed updated #7 {TITLE}"))
        self.assertEqual(gh.verbs(), [["issue", "create"]])

    def test_the_issue_is_labelled(self):
        gh = FakeGh([])
        issues_main.sync({"findings": [ROW], "errors": []}, "o/r", gh)
        create = gh.calls[-1]
        self.assertEqual(create[create.index("--label") + 1], issues_main.LABEL)


class TestBody(TestCase):
    def test_every_engine_gets_a_row(self):
        text = issues_main.body([ROW, {**ROW, "engine": "trivy"}])
        self.assertEqual(
            sum(
                1
                for line in text.splitlines()
                if line.startswith(("| grype", "| trivy"))
            ),
            2,
        )


if __name__ == "__main__":
    main()
