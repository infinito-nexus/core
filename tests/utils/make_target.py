from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from utils.cache import PROJECT_ROOT
from utils.cache.files import read_text

MAKEFILE = PROJECT_ROOT / "Makefile"
LOADER = Path("scripts") / "meta" / "env" / "load.sh"
SUDO = '#!/usr/bin/env bash\nexec "$@"\n'


def _logging(name: str, status: str, logged_env: bool) -> str:
    """
    Args:
        name: the name the stub logs its call under.
        status: the shell expression of its exit status.
        logged_env: whether it also logs the variables STUB_ENV names.

    Returns:
        The body of a stub that appends one line per call to STUB_LOG.
    """
    env = (
        'for name in ${STUB_ENV-}; do line="${line} ${name}=${!name-}"; done\n'
        if logged_env
        else ""
    )
    return (
        "#!/usr/bin/env bash\n"
        f'line="{name}"\n'
        'for arg in "$@"; do line="${line} $(printf %q "${arg}")"; done\n'
        f"{env}"
        'printf "%s\\n" "${line}" >>"${STUB_LOG}"\n'
        f'exit "{status}"\n'
    )


def run_target(
    target: str,
    arguments: tuple[str, ...],
    scripts: tuple[str, ...],
    env: dict[str, str],
) -> tuple[subprocess.CompletedProcess, list[str]]:
    """
    Args:
        target: the make target of the repository Makefile, run in an empty
            directory.
        arguments: the make command-line arguments after it.
        scripts: repository-relative scripts its recipe calls; each becomes a
            stub that logs its call under that path.
        env: the variables of the run beside PATH and the stubs; STUB_ENV names
            the variables a script stub logs after its arguments,
            STUB_PYTHON_RC the exit status of the stubbed interpreter.

    Returns:
        The finished make run and every stub call in order; the interpreter
        logs as ``python`` and a recursive make as ``make``.
    """
    real_make = shutil.which("make")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        bin_dir = root / ".stub-bin"
        log = root / ".stub-calls.log"
        log.touch()
        python = _logging("python", "${STUB_PYTHON_RC:-0}", False)
        stubs = {
            bin_dir / "python": python,
            bin_dir / "python3": python,
            bin_dir / "make": _logging("make", "0", False),
            bin_dir / "sudo": SUDO,
            root / LOADER: "",
            **{root / script: _logging(script, "0", True) for script in scripts},
        }
        for path, body in stubs.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding="utf-8")
            path.chmod(0o755)
        done = subprocess.run(
            [
                "make",
                "-e",
                "-s",
                "--no-print-directory",
                "-f",
                str(MAKEFILE),
                "-C",
                str(root),
                target,
                *arguments,
            ],
            executable=real_make,
            env={
                "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
                "BASH_ENV": "",
                "PYTHON": str(bin_dir / "python"),
                "STUB_LOG": str(log),
                **env,
            },
            capture_output=True,
            text=True,
            check=False,
        )
        return done, read_text(str(log)).splitlines()
