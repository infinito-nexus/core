from __future__ import annotations

import json
import random
import re
import shutil
import time
from typing import TYPE_CHECKING

from .github import gh_proc

if TYPE_CHECKING:
    from pathlib import Path

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def jitter(delay_max: float) -> None:
    # Spread the gh API calls over time to avoid rate limits; not security sensitive.
    time.sleep(random.uniform(1, delay_max))  # noqa: S311


def download_log(
    owner: str, repo: str, job: dict, dest: Path, delay_max: float
) -> tuple[str, bool]:
    jitter(delay_max)
    safe = _SAFE.sub("-", job["name"]).strip("-")
    proc = gh_proc(["api", f"repos/{owner}/{repo}/actions/jobs/{job['id']}/logs"])
    if proc.returncode != 0 or not proc.stdout:
        return job["name"], False
    (dest / f"{job['id']}__{safe}.log").write_text(proc.stdout, encoding="utf-8")
    return job["name"], True


def download_artifact(
    owner: str, repo: str, run: str, name: str, dest: Path, delay_max: float
) -> tuple[str, bool]:
    jitter(delay_max)
    target = dest / name
    # gh refuses to extract over existing files, so clear the dir for re-runs.
    shutil.rmtree(target, ignore_errors=True)
    proc = gh_proc(
        ["run", "download", run, "-R", f"{owner}/{repo}", "-n", name, "-D", str(target)]
    )
    return name, proc.returncode == 0


def write_manifest(jobs: list[dict], dest: Path) -> None:
    (dest / "jobs.json").write_text(json.dumps(jobs, indent=2), encoding="utf-8")
    rows = ["id\tconclusion\tstatus\tname"]
    rows += [
        "\t".join(
            [
                str(j.get("id", "")),
                j.get("conclusion") or "",
                j.get("status") or "",
                j.get("name") or "",
            ]
        )
        for j in jobs
    ]
    (dest / "summary.tsv").write_text("\n".join(rows) + "\n", encoding="utf-8")
