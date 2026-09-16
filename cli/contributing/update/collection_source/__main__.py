#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory

from utils.update.collection_source import (
    RATIO,
    SOURCES,
    WINDOW,
    append_sample,
    decide,
    load_history,
)

from . import PROJECT_ROOT

SETTING = "INFINITO_ANSIBLE_COLLECTIONS_SOURCE"
REQUIREMENTS = {
    "galaxy": Path("requirements/requirements.galaxy.yml"),
    "git": Path("requirements/requirements.git.yml"),
}


def read_preferred(env_file: Path) -> str:
    """The source currently tried first, as declared in default.env.

    Args:
        env_file: the default.env holding the setting.
    """
    match = re.search(
        rf"^{SETTING}=(\S+)\s*$",
        env_file.read_text(
            encoding="utf-8"
        ),  # nocheck: cache-read -- write_preferred rewrites this file in the same run
        re.MULTILINE,
    )
    if match is None:
        raise SystemExit(f"{SETTING} is not declared in {env_file}")
    return match.group(1)


def write_preferred(env_file: Path, source: str) -> None:
    """Point the setting at SOURCE.

    Args:
        env_file: the default.env holding the setting.
        source: the source to try first from now on.
    """
    text = env_file.read_text(
        encoding="utf-8"
    )  # nocheck: cache-read -- rewritten on the next line
    env_file.write_text(
        re.sub(rf"^{SETTING}=\S+$", f"{SETTING}={source}", text, flags=re.MULTILINE),
        encoding="utf-8",
    )


def measure(repo_root: Path, requirements: Path, timeout: int) -> float | None:
    """Seconds a cold install from REQUIREMENTS takes, or None when it fails.

    Args:
        repo_root: repository root the requirements path is relative to.
        requirements: the requirements file to install from.
        timeout: seconds after which the install counts as failed.
    """
    with TemporaryDirectory() as target:
        started = time.monotonic()
        try:
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "ansible.cli.galaxy",
                    "collection",
                    "install",
                    "-r",
                    str(repo_root / requirements),
                    "-p",
                    target,
                    "--force-with-deps",
                ],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return None
        elapsed = time.monotonic() - started
    return elapsed if completed.returncode == 0 else None


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Time both collection sources, record the sample, and retune the "
            "preferred default when one source is durably slower."
        )
    )
    parser.add_argument("--repo-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument(
        "--history",
        type=Path,
        default=None,
        help="JSON file holding the rolling window of samples",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=900,
        help="Seconds after which one install counts as failed",
    )
    args = parser.parse_args()

    repo_root = args.repo_root.resolve()
    env_file = repo_root / "default.env"
    history_file = (
        args.history or repo_root / "build" / "collection-source-history.json"
    )

    sample: dict[str, float | None] = {}
    for source in SOURCES:
        seconds = measure(repo_root, REQUIREMENTS[source], args.timeout)
        sample[source] = seconds
        print(f"{source}: {'failed' if seconds is None else f'{seconds:.1f}s'}")

    history = append_sample(load_history(history_file), sample)
    history_file.parent.mkdir(parents=True, exist_ok=True)
    history_file.write_text(json.dumps(history, indent=2), encoding="utf-8")

    preferred = read_preferred(env_file)
    verdict = decide(history, preferred)
    print(
        f"samples: {verdict.samples}/{WINDOW}, "
        f"medians: {verdict.medians}, preferred: {verdict.preferred}"
    )

    if not verdict.changed:
        print("Preferred collection source stays unchanged.")
        return 0

    write_preferred(env_file, verdict.proposed)
    print(
        f"Preferred collection source {verdict.preferred} -> {verdict.proposed}: "
        f"its median is at least {RATIO}x the other's over {WINDOW} samples."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
