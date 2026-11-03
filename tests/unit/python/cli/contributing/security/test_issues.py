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
    "suppressed_until": None,
}
SUPPRESSED = {**ROW, "id": "CVE-2026-109619", "suppressed_until": "2026-12-03"}
TITLE = "🛡️ docker.io/roundcube/roundcubemail:1.7.5-apache"
OTHER_IMAGE = "docker.io/library/nginx:1.31.8-alpine"


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

    def test_a_changed_image_gets_a_comment_and_an_updated_body(self):
        gh = FakeGh([{"number": 7, "title": TITLE, "body": "old table"}])
        issues_main.sync({"findings": [ROW], "errors": []}, "o/r", gh)
        self.assertEqual(gh.verbs(), [["issue", "comment"], ["issue", "edit"]])
        comment = gh.calls[-2]
        self.assertIn("Still unresolved:", comment[comment.index("--body") + 1])
        self.assertIn(ROW["id"], comment[comment.index("--body") + 1])

    def test_an_unchanged_image_leaves_its_issue_alone(self):
        current = issues_main.body([ROW])
        gh = FakeGh([{"number": 7, "title": TITLE, "body": current + "\r\n"}])
        actions = issues_main.sync({"findings": [ROW], "errors": []}, "o/r", gh)
        self.assertEqual((gh.verbs(), actions), ([], [f"unchanged #7 {TITLE}"]))

    def test_a_second_open_issue_of_one_image_closes_as_duplicate(self):
        current = issues_main.body([ROW])
        gh = FakeGh(
            [
                {"number": 9, "title": TITLE, "body": current},
                {"number": 7, "title": TITLE, "body": current},
            ]
        )
        actions = issues_main.sync({"findings": [ROW], "errors": []}, "o/r", gh)
        self.assertEqual(gh.verbs(), [["issue", "close"]])
        self.assertEqual(gh.calls[-1][2], "9")
        self.assertIn(f"unchanged #7 {TITLE}", actions)

    def test_a_fixed_finding_closes_its_issue(self):
        gh = FakeGh([{"number": 7, "title": TITLE}])
        actions = issues_main.sync({"findings": [], "errors": []}, "o/r", gh)
        self.assertEqual(actions, [f"closed #7 {TITLE}"])

    def test_a_suppressed_finding_keeps_its_issue_open(self):
        gh = FakeGh([{"number": 7, "title": TITLE, "body": "old table"}])
        actions = issues_main.sync({"findings": [SUPPRESSED], "errors": []}, "o/r", gh)
        self.assertEqual(gh.verbs(), [["issue", "comment"], ["issue", "edit"]])
        self.assertNotIn(f"closed #7 {TITLE}", actions)

    def test_a_scan_error_closes_nothing(self):
        gh = FakeGh([{"number": 7, "title": TITLE}])
        issues_main.sync(
            {"findings": [], "errors": ["x: the mirror served no digest"]}, "o/r", gh
        )
        self.assertEqual(gh.verbs(), [])

    def test_a_failed_issue_call_is_reported_and_the_others_still_run(self):
        other = {**ROW, "image": OTHER_IMAGE}
        gh = FakeGh([{"number": 7, "title": TITLE}], hang=[("issue", "edit")])
        actions = issues_main.sync({"findings": [ROW, other], "errors": []}, "o/r", gh)
        failed = [action for action in actions if action.startswith("failed ")]
        self.assertEqual(len(failed), 1)
        self.assertTrue(failed[0].startswith(f"failed updated #7 {TITLE}"))
        self.assertEqual(gh.verbs(), [["issue", "create"], ["issue", "comment"]])

    def test_every_cve_of_one_image_shares_one_issue(self):
        gh = FakeGh([])
        actions = issues_main.sync(
            {
                "findings": [ROW, {**ROW, "id": "CVE-2026-109619"}],
                "errors": [],
            },
            "o/r",
            gh,
        )
        self.assertEqual(actions, [f"opened {TITLE}"])

    def test_the_issue_is_labelled(self):
        gh = FakeGh([])
        issues_main.sync({"findings": [ROW], "errors": []}, "o/r", gh)
        create = gh.calls[-1]
        self.assertEqual(create[create.index("--label") + 1], issues_main.LABEL)


class TestBody(TestCase):
    def _table(self, text):
        return [line for line in text.splitlines() if line.startswith("| CVE-")]

    def test_every_engine_gets_a_row(self):
        text = issues_main.body([ROW, {**ROW, "engine": "trivy"}])
        self.assertEqual(len(self._table(text)), 2)

    def test_critical_rows_come_first(self):
        high = {**ROW, "id": "CVE-2026-000001", "severity": "HIGH"}
        table = self._table(issues_main.body([high, ROW]))
        self.assertIn("| CRITICAL |", table[0])

    def test_a_suppressed_cve_is_listed_after_the_failing_ones_with_its_until(self):
        text = issues_main.body([SUPPRESSED, ROW])
        table = self._table(text)
        self.assertEqual(
            (table[0].endswith("| - |"), table[1].endswith("| 2026-12-03 |")),
            (True, True),
        )
        self.assertIn(
            "carries 2 CVE(s) at the scan threshold, 1 of them suppressed.", text
        )

    def test_a_large_image_stays_under_the_body_limit(self):
        rows = [{**ROW, "id": f"CVE-2026-{index:06d}"} for index in range(2000)]
        text = issues_main.body(rows)
        self.assertLessEqual(len(text), issues_main.BODY_LIMIT)
        hidden = 2000 - len(self._table(text))
        self.assertGreater(hidden, 0)
        self.assertIn(f"{hidden} more row(s)", text)


if __name__ == "__main__":
    main()
