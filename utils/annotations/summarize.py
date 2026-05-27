#!/usr/bin/env python3
"""Parse GHA annotation lines from a log file and write a Markdown summary
to $GITHUB_STEP_SUMMARY.

Usage:
    python3 -m utils.annotations.summarize <logfile> [<title>]

Annotation format emitted by utils.annotations.message:
    ::warning title=<t>,file=<f>,line=<l>,col=<c>::<message>
    ::error   title=<t>,...::<message>
    ::notice  title=<t>,...::<message>
"""

from __future__ import annotations

import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from utils.cache.files import read_text

ANNOTATION_RE = re.compile(r"^::(warning|error|notice)(?:\s([^:]*))?::(.*)$")
PROP_RE = re.compile(r"(\w+)=([^,]*)")

ICONS = {"error": "🔴", "warning": "🟡", "notice": "🔵"}
HEADINGS = {"error": "Errors", "warning": "Warnings", "notice": "Notices"}


@dataclass
class Annotation:
    level: str
    message: str
    title: str | None = None
    file: str | None = None
    line: int | None = None
    col: int | None = None


def parse_props(props_str: str) -> dict[str, str]:
    return {m.group(1): m.group(2) for m in PROP_RE.finditer(props_str or "")}


def parse_log(path: Path) -> list[Annotation]:
    annotations: list[Annotation] = []
    try:
        content = read_text(str(path))
    except UnicodeDecodeError:
        return annotations
    for raw in content.splitlines():
        m = ANNOTATION_RE.match(raw.strip())
        if not m:
            continue
        level, props_str, message = m.group(1), m.group(2) or "", m.group(3)
        props = parse_props(props_str)
        annotations.append(
            Annotation(
                level=level,
                message=message,
                title=props.get("title"),
                file=props.get("file"),
                line=int(props["line"]) if "line" in props else None,
                col=int(props["col"]) if "col" in props else None,
            )
        )
    return annotations


def render_markdown(annotations: list[Annotation], title: str) -> str:
    if not annotations:
        return f"## {title}\n\n✅ No annotations found.\n"

    by_level: dict[str, list[Annotation]] = defaultdict(list)
    for a in annotations:
        by_level[a.level].append(a)

    lines = [f"## {title}\n"]
    for level in ("error", "warning", "notice"):
        items = by_level.get(level, [])
        if not items:
            continue
        icon = ICONS[level]
        heading = HEADINGS[level]
        lines.append(f"### {icon} {heading} ({len(items)})\n")
        lines.append("| Title | File | Message |")
        lines.append("|-------|------|---------|")
        for a in items:
            t = a.title or ""
            loc = a.file or ""
            if loc and a.line:
                loc = f"{loc}:{a.line}"
            msg = a.message.replace("|", "\\|")
            lines.append(f"| {t} | {loc} | {msg} |")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: summarize <logfile> [<title>]", file=sys.stderr)
        sys.exit(1)

    log_path = Path(sys.argv[1])
    title = sys.argv[2] if len(sys.argv) > 2 else "Annotation Summary"

    if not log_path.exists():
        print(f"Log file not found, skipping summary: {log_path}", file=sys.stderr)
        sys.exit(0)

    annotations = parse_log(log_path)
    markdown = render_markdown(annotations, title)

    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_file:
        with Path(summary_file).open("a") as f:
            f.write(markdown + "\n")
    else:
        print(markdown)


if __name__ == "__main__":
    main()
