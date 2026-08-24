"""Open (or comment on) a 'CI failure: <role>' issue per role whose deploy failed, linking the run artifacts and inlining the decisive rescue excerpt."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

from utils.cache.files import read_text
from utils.github.variant import axes
from utils.roles.display import display_names

_DECISIVE_FILES = ("error-context.md", "meta.txt", "containers.txt")
_TITLE = "CI failure: {role}"
_LABEL = "ci-failure"


class Failure(NamedTuple):
    """The combination one red deploy job died on -- everything the artifact
    name is built from, so the reporter downloads the run it is reporting."""

    mode: str
    variant: str
    tor: bool
    distro: str
    filesystem: str


def failed_roles(jobs: list[dict]) -> dict[str, list[Failure]]:
    """Map role -> [:class:`Failure`] for every failed deploy job.

    A deploy job is titled ``<mode glyph><tor glyph><distro glyph><filesystem
    glyph><display name> <variant>`` with an optional trailing ⭐ for a
    priority row. The middle is resolved through the display-name codec rather
    than matched as a raw role id: job names carry display names, so a regex
    over ``web-app-…`` silently matched nothing and every failure went
    unreported.
    """
    codec = display_names()
    out: dict[str, list[Failure]] = {}
    for job in jobs:
        if job.get("conclusion") not in ("failure", "timed_out"):
            continue
        label = axes.parse_label(str(job.get("name", "")))
        if label is None:
            continue
        role = codec.decode(label.name)
        if role is None:
            continue
        out.setdefault(role, []).append(
            Failure(
                label.mode,
                label.variant.replace(",", "-"),
                label.tor,
                label.distro,
                label.filesystem,
            )
        )
    return out


def artifact_name(role: str, failure: Failure) -> str:
    """The rescue-diagnostics artifact one deploy job uploads.

    The slug comes from :func:`axes.artifact_slug`, the same call the matrix
    entry carries into the workflow, so the name this looks for and the name
    CI uploads cannot drift apart.
    """
    return "rescue-diagnostics-" + axes.artifact_slug(
        failure.mode,
        role,
        failure.variant,
        failure.tor,
        failure.distro,
        failure.filesystem,
    )


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
    failures: list[Failure],
    *,
    run_url: str,
    excerpt: str,
) -> str:
    rows = "\n".join(
        f"- `{failure.mode}`"
        + (f" variant `{failure.variant}`" if failure.variant else "")
        + (" behind the onion" if failure.tor else "")
        + (f" on `{failure.distro}`" if failure.distro else "")
        + (f"/`{failure.filesystem}`" if failure.filesystem else "")
        + f" — artifact `{artifact_name(role, failure)}`"
        for failure in failures
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
    repo: str, run_id: str, role: str, failures: list[Failure], dest: Path
) -> str:
    for failure in failures:
        name = artifact_name(role, failure)
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
