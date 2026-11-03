import os
import re
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT, read_text

SCRIPT = PROJECT_ROOT / "roles/dev-python/files/shell/install.sh"
ROLE_TASKS = PROJECT_ROOT / "roles/dev-python/tasks/00_core.yml"


def _call(
    snippet: str, *args: str, requires: str | None = None
) -> subprocess.CompletedProcess:
    """Source install.sh without running its entrypoint, then run a snippet.

    Args:
        snippet: bash code evaluated after sourcing; sees ``args`` as ``"$@"``.
        args: positional arguments handed to the snippet.
        requires: value for ``INFINITO_PYTHON_REQUIRES``; ``None`` leaves it
            unset so the script reads the repository's ``pyproject.toml``.

    Returns:
        The completed bash process.
    """
    env = {
        key: value
        for key, value in os.environ.items()
        if key != "INFINITO_PYTHON_REQUIRES"
    }
    if requires is not None:
        env["INFINITO_PYTHON_REQUIRES"] = requires
    return subprocess.run(
        ["bash", "-c", f'source "$1"; shift; {snippet}', "bash", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def _declared_minors() -> tuple[int, int]:
    spec = tomllib.loads(read_text(str(PROJECT_ROOT / "pyproject.toml")))["project"][
        "requires-python"
    ]
    match = re.fullmatch(r">=3\.(\d+),<3\.(\d+)", spec)
    return int(match[1]), int(match[2]) - 1


def _bound(name: str) -> int:
    return int(_call(f'printf "%s" "${name}"').stdout)


def _fake_python(directory: Path, minor: int, *, pip: bool) -> str:
    """Write an executable that answers the interpreter probes of install.sh.

    Args:
        directory: directory the fake is written to.
        minor: Python 3 minor version the fake reports.
        pip: whether ``-m pip --version`` succeeds.

    Returns:
        Absolute path of the fake interpreter.
    """
    path = directory / f"python3.{minor}"
    path.write_text(
        "#!/bin/sh\n"
        f'if [ "$1" = "-m" ]; then exit {0 if pip else 1}; fi\n'
        "cat >/dev/null\n"
        f"echo 3.{minor}\n"
    )
    path.chmod(0o755)
    return str(path)


class _InterpreterCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.floor = _bound("PYTHON_MIN_MINOR")
        self.cap = _bound("PYTHON_MAX_MINOR")

    def fake(self, minor: int, *, pip: bool = True) -> str:
        return _fake_python(self.dir, minor, pip=pip)


class TestPickBestPython(_InterpreterCase):
    def pick(self, *candidates: str) -> subprocess.CompletedProcess:
        return _call('pick_best_python "$@"', *candidates)

    def test_skips_a_minor_above_the_cap(self) -> None:
        capped = self.fake(self.cap)
        result = self.pick(capped, self.fake(self.cap + 1))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), capped)

    def test_ignores_pip_on_a_minor_above_the_cap(self) -> None:
        capped = self.fake(self.cap, pip=False)
        result = self.pick(
            self.fake(self.cap - 1, pip=False), capped, self.fake(self.cap + 1)
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), capped)

    def test_picks_the_highest_minor_within_bounds(self) -> None:
        highest = self.fake(self.cap)
        result = self.pick(self.fake(self.cap - 2), self.fake(self.cap - 1), highest)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), highest)

    def test_prefers_a_lower_minor_that_has_pip(self) -> None:
        with_pip = self.fake(self.cap - 1)
        result = self.pick(with_pip, self.fake(self.cap, pip=False))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), with_pip)

    def test_fails_when_only_minors_above_the_cap_exist(self) -> None:
        result = self.pick(self.fake(self.cap + 1))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_fails_when_only_minors_below_the_floor_exist(self) -> None:
        result = self.pick(self.fake(self.floor - 1))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")


class TestResolvePythonBinOrFail(_InterpreterCase):
    def test_names_the_supported_range_when_only_a_newer_minor_exists(self) -> None:
        result = _call(
            'candidates=("$@"); '
            'pick_python_bin() { pick_best_python "${candidates[@]}"; }; '
            "resolve_python_bin_or_fail",
            self.fake(self.cap + 1),
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn(f"3.{self.floor} to 3.{self.cap}", result.stderr)


class TestFindHighestPythonPackage(unittest.TestCase):
    def setUp(self) -> None:
        self.cap = _bound("PYTHON_MAX_MINOR")

    def rpm(self, *minors: int) -> subprocess.CompletedProcess:
        listing = "Available packages\n" + "".join(
            f"python3.{m}.x86_64  3.{m}.0-1.fc45  fedora\n"
            f"python3.{m}-devel.x86_64  3.{m}.0-1.fc45  fedora\n"
            for m in minors
        )
        return _call(
            'listing="$1"; '
            'run_privileged() { "$@"; }; '
            'dnf() { printf "%s" "${listing}"; }; '
            "find_highest_rpm_python_pkg dnf",
            listing,
        )

    def apt(self, *minors: int) -> subprocess.CompletedProcess:
        names = ["python3", "python3-pip"] + [f"python3.{m}" for m in minors]
        return _call(
            'names=("$@"); '
            'apt-cache() { printf "%s\\n" "${names[@]}"; }; '
            "find_highest_apt_python_pkg",
            *names,
        )

    def test_rpm_skips_a_package_above_the_cap(self) -> None:
        result = self.rpm(self.cap - 1, self.cap, self.cap + 1)
        self.assertEqual(result.stdout.strip(), f"python3.{self.cap}")

    def test_rpm_yields_nothing_when_only_packages_above_the_cap_exist(self) -> None:
        result = self.rpm(self.cap + 1)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_apt_skips_a_package_above_the_cap(self) -> None:
        result = self.apt(self.cap - 1, self.cap, self.cap + 1)
        self.assertEqual(result.stdout.strip(), f"python3.{self.cap}")

    def test_apt_keeps_the_highest_package_within_bounds(self) -> None:
        result = self.apt(self.cap - 2, self.cap - 1)
        self.assertEqual(result.stdout.strip(), f"python3.{self.cap - 1}")


class TestBoundsFromRequiresPython(unittest.TestCase):
    def test_the_bounds_come_from_pyproject_requires_python(self) -> None:
        self.assertEqual(
            (_bound("PYTHON_MIN_MINOR"), _bound("PYTHON_MAX_MINOR")),
            _declared_minors(),
        )

    def test_the_role_hands_requires_python_to_the_remote_script(self) -> None:
        result = _call(
            'printf "%s %s" "$PYTHON_MIN_MINOR" "$PYTHON_MAX_MINOR"',
            requires=">=3.12,<3.14",
        )
        self.assertEqual(result.stdout, "12 13")
        self.assertIn("INFINITO_PYTHON_REQUIRES", read_text(str(ROLE_TASKS)))

    def test_an_unsupported_requires_python_form_fails_loudly(self) -> None:
        result = _call("true", requires=">=3.11")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must read >=3.X,<3.Y", result.stderr)


if __name__ == "__main__":
    unittest.main()
