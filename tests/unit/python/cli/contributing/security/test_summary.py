from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest import TestCase, main

import cli.contributing.security.summary.__main__ as summary_main
from utils.cache.files import read_text


def _row(image, cve, engine="grype"):
    return {"image": image, "id": cve, "engine": engine}


REPORT = {
    "findings": [
        _row("docker.io/a:1", "CVE-2026-1001"),
        _row("docker.io/a:1", "CVE-2026-1001", engine="trivy"),
        _row("docker.io/a:1", "CVE-2026-1002"),
        _row("docker.io/b:2", "CVE-2026-1001"),
    ],
    "errors": ["docker.io/c:3: the mirror served no digest"],
}


class TestCounts(TestCase):
    def test_an_image_counts_its_distinct_cves(self):
        self.assertEqual(
            summary_main.counts(REPORT)["per_image"]["docker.io/a:1"],
            {"cves": 2, "findings": 3},
        )

    def test_a_cve_counts_its_distinct_images(self):
        self.assertEqual(
            summary_main.counts(REPORT)["per_cve"]["CVE-2026-1001"],
            {"images": 2, "findings": 3},
        )

    def test_totals_include_the_scan_errors(self):
        counts = summary_main.counts(REPORT)
        self.assertEqual((counts["findings"], counts["errors"]), (4, 1))


class TestMarkdown(TestCase):
    def test_the_most_affected_image_comes_first(self):
        text = summary_main.markdown(summary_main.counts(REPORT))
        self.assertLess(text.index("docker.io/a:1"), text.index("docker.io/b:2"))

    def test_the_headline_names_the_totals(self):
        text = summary_main.markdown(summary_main.counts(REPORT))
        self.assertIn(
            "4 failing finding(s) in 2 image(s), 2 CVE(s), 1 scan error(s).", text
        )


class TestMain(TestCase):
    def test_the_counts_artifact_and_the_summary_are_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "report.json").write_text(json.dumps(REPORT), encoding="utf-8")
            summary_main.main(
                [
                    "--report",
                    str(root / "report.json"),
                    "--counts",
                    str(root / "counts.json"),
                    "--summary",
                    str(root / "summary.md"),
                ]
            )
            counts = json.loads(read_text(str(root / "counts.json")))
            text = read_text(str(root / "summary.md"))
        self.assertEqual(counts["findings"], 4)
        self.assertIn("Vulnerability scan of the mirror", text)


if __name__ == "__main__":
    main()
