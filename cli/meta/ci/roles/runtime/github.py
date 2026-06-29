from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from cli.administration.deploy.ci.runs import app_of_job

from .csvio import read_csv

if TYPE_CHECKING:
    from .model import RoleRuntime

_URL_RE = re.compile(
    r"github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/actions/runs/(?P<run>\d+)"
    r"(?:/job/(?P<job>\d+))?"
)


def parse_run_ref(url: str) -> tuple[str, str, str, str | None]:
    """Return (owner, repo, run_id, job_id|None) from a run/job URL."""
    m = _URL_RE.search(url)
    if not m:
        raise ValueError(f"not a GitHub Actions run/job URL: {url}")
    return m.group("owner"), m.group("repo"), m.group("run"), m.group("job")


def _gh(args: list[str]) -> str:
    return subprocess.run(
        ["gh", *args], capture_output=True, text=True, check=True
    ).stdout


def app_for_job(owner: str, repo: str, job: str) -> str:
    """Resolve the matrix app id from a deploy job's display name."""
    name = _gh(
        ["api", f"repos/{owner}/{repo}/actions/jobs/{job}", "--jq", ".name"]
    ).strip()
    return app_of_job(name) or name


def records_from_job_url(url: str) -> list[RoleRuntime]:
    """Download the `role-runtimes-*` CSV artifact(s) for a run/job URL.

    A job URL narrows the download to that job's app; a bare run URL pulls
    every `role-runtimes-*` artifact in the run.
    """
    owner, repo, run, job = parse_run_ref(url)
    with tempfile.TemporaryDirectory() as tmp:
        args = ["run", "download", run, "-R", f"{owner}/{repo}", "-D", tmp]
        if job:
            args += ["-n", f"role-runtimes-{app_for_job(owner, repo, job)}"]
        else:
            args += ["--pattern", "role-runtimes-*"]
        subprocess.run(["gh", *args], check=True)
        records: list[RoleRuntime] = []
        for csv_file in sorted(Path(tmp).rglob("role-runtimes-*.csv")):
            records.extend(read_csv(csv_file))
        return records
