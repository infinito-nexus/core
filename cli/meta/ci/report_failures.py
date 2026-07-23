"""Open (or comment on) a 'CI failure: <role>' issue per role whose deploy failed, linking the run artifacts and inlining the decisive rescue excerpt."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from utils.cache.files import read_text
from utils.symbol_glossary import to_emoji, to_word

_MODES = ("swarm", "compose", "host")
_ROLE_RE = re.compile(
    r"(" + "|".join(re.escape(to_emoji(m)) for m in _MODES) + r")️?\s+"
    r"((?:web-app|web-svc|svc|sys)-[a-z0-9-]+?)(?:\s+([0-9,]+))?\s*$"
)
_DECISIVE_FILES = ("error-context.md", "meta.txt", "containers.txt")
_TITLE = "CI failure: {role}"
_LABEL = "ci-failure"


def failed_roles(jobs: list[dict]) -> dict[str, list[tuple[str, str]]]:
    """Map role -> [(mode, variant)] for every failed deploy job in *jobs*."""
    out: dict[str, list[tuple[str, str]]] = {}
    for job in jobs:
        if job.get("conclusion") not in ("failure", "timed_out"):
            continue
        match = _ROLE_RE.search(job.get("name", ""))
        if match is None:
            continue
        mode = to_word(match.group(1))
        role = match.group(2)
        variant = (match.group(3) or "").replace(",", "-")
        out.setdefault(role, []).append((mode, variant))
    return out


def artifact_name(mode: str, role: str, variant: str) -> str:
    suffix = f"-{variant}" if variant else ""
    return f"rescue-diagnostics-{mode}-{role}{suffix}"


def decisive_excerpt(rescue_dir: Path, *, max_lines: int = 40) -> str:
    """First error-context / meta / containers file in *rescue_dir*, truncated."""
    for wanted in _DECISIVE_FILES:
        for path in sorted(rescue_dir.rglob(wanted)):
            try:
                lines = read_text(str(path)).splitlines()
            except (OSError, UnicodeDecodeError):
                continue
            body = "\n".join(lines[:max_lines])
            if body.strip():
                more = "\n... (truncated)" if len(lines) > max_lines else ""
                return f"`{path.name}`:\n```\n{body}{more}\n```"
    return "_No decisive rescue file captured (container torn down before capture)._"


def issue_body(
    role: str,
    failures: list[tuple[str, str]],
    *,
    run_url: str,
    excerpt: str,
) -> str:
    rows = "\n".join(
        f"- `{mode}`"
        + (f" variant `{variant}`" if variant else "")
        + f" — artifact `{artifact_name(mode, role, variant)}`"
        for mode, variant in failures
    )
    return (
        f"Role **{role}** failed on `main`.\n\n"
        f"Run: {run_url}\n\n"
        f"Failed deploys:\n{rows}\n\n"
        f"Download the artifacts from the run page above.\n\n"
        f"{excerpt}\n"
    )


def _gh(args: list[str]) -> str:
    return subprocess.run(
        ["gh", *args], capture_output=True, text=True, check=True
    ).stdout


def _existing_issue(repo: str, role: str) -> int | None:
    out = _gh(
        [
            "issue",
            "list",
            "--repo",
            repo,
            "--state",
            "open",
            "--label",
            _LABEL,
            "--search",
            _TITLE.format(role=role),
            "--json",
            "number,title",
        ]
    )
    for issue in json.loads(out or "[]"):
        if issue.get("title") == _TITLE.format(role=role):
            return int(issue["number"])
    return None


def report(run_id: str, repo: str) -> int:
    jobs = json.loads(
        _gh(
            [
                "api",
                "--paginate",
                f"repos/{repo}/actions/runs/{run_id}/jobs",
                "--jq",
                "[.jobs[] | {name, conclusion}]",
            ]
        )
        or "[]"
    )
    roles = failed_roles(jobs)
    if not roles:
        print("No failed deploy roles.")
        return 0
    _gh(
        [
            "label",
            "create",
            _LABEL,
            "--repo",
            repo,
            "--force",
            "--color",
            "d73a4a",
            "--description",
            "A role deploy failed on main",
        ]
    )
    run_url = f"https://github.com/{repo}/actions/runs/{run_id}"
    for role, failures in sorted(roles.items()):
        dest = Path(f"rescue-{role}")
        excerpt = _download_excerpt(repo, run_id, role, failures, dest)
        body = issue_body(role, failures, run_url=run_url, excerpt=excerpt)
        number = _existing_issue(repo, role)
        if number is None:
            _gh(
                [
                    "issue",
                    "create",
                    "--repo",
                    repo,
                    "--label",
                    _LABEL,
                    "--title",
                    _TITLE.format(role=role),
                    "--body",
                    body,
                ]
            )
            print(f"opened issue for {role}")
        else:
            _gh(["issue", "comment", str(number), "--repo", repo, "--body", body])
            print(f"commented on #{number} for {role}")
    return 0


def _download_excerpt(
    repo: str, run_id: str, role: str, failures: list[tuple[str, str]], dest: Path
) -> str:
    for mode, variant in failures:
        name = artifact_name(mode, role, variant)
        try:
            _gh(
                ["run", "download", run_id, "--repo", repo, "-n", name, "-D", str(dest)]
            )
        except subprocess.CalledProcessError:
            continue
    return decisive_excerpt(dest) if dest.is_dir() else _NO_ARTIFACT


_NO_ARTIFACT = "_No rescue-diagnostics artifact was uploaded for this role._"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Report main role failures.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--repo", required=True)
    args = parser.parse_args(argv)
    return report(args.run_id, args.repo)


if __name__ == "__main__":
    sys.exit(main())
