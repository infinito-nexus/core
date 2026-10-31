#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from utils.cache.files import read_text

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

TOP = 25


def counts(report: Mapping[str, Any]) -> dict[str, Any]:
    """Count the failing findings of a ``make test-security`` report.

    Returns:
        ``findings`` and ``errors`` totals, plus per image and per CVE the
        distinct CVEs or images and the finding rows behind them.
    """
    images: dict[str, dict[str, set[str] | int]] = {}
    cves: dict[str, dict[str, set[str] | int]] = {}
    for row in report["findings"]:
        image = images.setdefault(row["image"], {"cves": set(), "findings": 0})
        image["cves"].add(row["id"])
        image["findings"] += 1
        cve = cves.setdefault(row["id"], {"images": set(), "findings": 0})
        cve["images"].add(row["image"])
        cve["findings"] += 1
    return {
        "findings": len(report["findings"]),
        "errors": len(report["errors"]),
        "per_image": {
            name: {"cves": len(entry["cves"]), "findings": entry["findings"]}
            for name, entry in sorted(images.items())
        },
        "per_cve": {
            name: {"images": len(entry["images"]), "findings": entry["findings"]}
            for name, entry in sorted(cves.items())
        },
    }


def _table(
    title: str, rows: Iterable[tuple[str, int, int]], columns: tuple[str, str, str]
) -> list[str]:
    lines = [f"### {title}", "", f"| {' | '.join(columns)} |", "|---|---|---|"]
    lines.extend(f"| `{name}` | {first} | {second} |" for name, first, second in rows)
    return [*lines, ""]


def markdown(summary: Mapping[str, Any]) -> str:
    """Render :func:`counts` as a job summary, largest first."""
    per_image = sorted(
        summary["per_image"].items(), key=lambda item: (-item[1]["cves"], item[0])
    )
    per_cve = sorted(
        summary["per_cve"].items(), key=lambda item: (-item[1]["images"], item[0])
    )
    lines = [
        "## 🔬 Vulnerability scan of the mirror",
        "",
        (
            f"{summary['findings']} failing finding(s) in {len(per_image)} image(s), "
            f"{len(per_cve)} CVE(s), {summary['errors']} scan error(s)."
        ),
        "",
    ]
    lines += _table(
        f"Images (top {TOP})",
        ((name, entry["cves"], entry["findings"]) for name, entry in per_image[:TOP]),
        ("image", "CVEs", "findings"),
    )
    lines += _table(
        f"CVEs (top {TOP})",
        ((name, entry["images"], entry["findings"]) for name, entry in per_cve[:TOP]),
        ("CVE", "images", "findings"),
    )
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Count the findings of a make test-security report per image and per CVE."
    )
    parser.add_argument("--report", required=True, help="The make test-security report")
    parser.add_argument("--counts", required=True, help="JSON file the counts go to")
    parser.add_argument(
        "--summary", required=True, help="Markdown file the summary is appended to"
    )
    args = parser.parse_args(argv)
    summary = counts(json.loads(read_text(args.report)))
    Path(args.counts).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    with Path(args.summary).open("a", encoding="utf-8") as handle:
        handle.write(markdown(summary) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
