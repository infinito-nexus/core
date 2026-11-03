import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT

SCRIPT = PROJECT_ROOT / "roles/dev-python/files/shell/install.sh"


def _call(snippet: str, *args: str) -> subprocess.CompletedProcess:
    """Source install.sh without running its entrypoint, then run a snippet.

    Args:
        snippet: bash code evaluated after sourcing; sees ``args`` as ``"$@"``.
        args: positional arguments handed to the snippet.

    Returns:
        The completed bash process.
    """
    return subprocess.run(
        ["bash", "-c", f'source "$1"; shift; {snippet}', "bash", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
    )


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


if __name__ == "__main__":
    unittest.main()
