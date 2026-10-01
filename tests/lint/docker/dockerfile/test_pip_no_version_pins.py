"""Lint: no role Dockerfile pins an exact version inside a ``pip install``.

A pin written into a ``RUN pip install name==version`` is invisible to every
updater the repository runs: dependabot's ``pip`` ecosystem
(``.github/dependabot.yml``) reads ``requirements*.txt`` and
``pyproject.toml``, and the repository's own pip updater reads the
``package_name:`` key of an Ansible task. A version frozen in a build recipe
therefore ages until somebody opens the Dockerfile by hand.

The pin belongs in a ``requirements.txt`` or ``pyproject.toml`` under the
role's ``files/``, staged into the build context and installed with
``pip install -r``. A ``--no-deps`` group needs its own requirements file,
because pip has no per-line ``--no-deps``.

Covers every tracked file under ``roles/`` named ``Dockerfile`` or
``Dockerfile.<something>``, template variants included. A pin counts only
inside the ``pip install`` command itself: the scan follows backslash
continuations but stops at the next shell separator (``&&``, ``||``, ``;``,
``|``), skips whole-line comments, and ignores a version supplied by an ``ARG``
or a Jinja expression, because the Dockerfile then holds no literal to raise.

Suppression (see ``docs/contributing/actions/testing/suppression.md``):

* ``# nocheck: dockerfile-pip-pin`` on, or directly above, the pinned line.
"""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path
from typing import ClassVar

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_non_ignored_files, read_text

from . import PROJECT_ROOT

_RULE = "dockerfile-pip-pin"

_REPO_ROOT = PROJECT_ROOT
_ROLES_ROOT = _REPO_ROOT / "roles"

_J2_CTRL_RE = re.compile(r"\{%-?.*?-?%\}")
_COMMENT_RE = re.compile(r"^\s*#")
_SEPARATOR_RE = re.compile(r"&&|\|\||;|\|")
_PIP_INSTALL_RE = re.compile(r"\bpip3?(?:\s+--?[\w.=/-]+)*\s+install\b")
_PIN_RE = re.compile(
    r"(?<![A-Za-z0-9._/-])(?P<package>[A-Za-z0-9][A-Za-z0-9._-]*)"
    r"(?P<extras>\[[A-Za-z0-9,._-]+\])?=="
    r"(?P<version>[0-9][0-9A-Za-z.+-]*)"
)


def _is_dockerfile(path: str) -> bool:
    name = Path(path).name
    return name == "Dockerfile" or name.startswith("Dockerfile.")


def collect_dockerfiles() -> list[Path]:
    """Return every tracked role Dockerfile, template variants included."""
    return sorted(
        path
        for path in (Path(candidate) for candidate in iter_non_ignored_files())
        if _is_dockerfile(str(path)) and path.is_relative_to(_ROLES_ROOT)
    )


def pinned_installs(dockerfile: Path) -> list[tuple[int, str, str]]:
    """Return ``(line_number, package, version)`` for every pin in a pip install.

    Args:
        dockerfile: the Dockerfile to scan.
    """
    lines = read_text(str(dockerfile)).splitlines()
    findings: list[tuple[int, str, str]] = []
    in_pip_install = False
    for number, raw in enumerate(lines, start=1):
        line = _J2_CTRL_RE.sub("", raw)
        if _COMMENT_RE.match(line):
            continue
        suppressed = is_suppressed_at(lines, number, _RULE)
        segments = _SEPARATOR_RE.split(line)
        for position, raw_segment in enumerate(segments):
            install = _PIP_INSTALL_RE.search(raw_segment)
            in_pip_install = in_pip_install or bool(install)
            segment = raw_segment[install.end() :] if install else raw_segment
            if in_pip_install and not suppressed:
                findings.extend(
                    (number, match.group("package"), match.group("version"))
                    for match in _PIN_RE.finditer(segment)
                )
            if position < len(segments) - 1:
                in_pip_install = False
        if not line.rstrip().endswith("\\"):
            in_pip_install = False
    return findings


class TestDockerfilePipNoVersionPins(unittest.TestCase):
    def test_dockerfiles_exist(self) -> None:
        self.assertTrue(
            collect_dockerfiles(),
            "no role Dockerfile found; the scan would pass vacuously",
        )

    def test_no_pip_install_pins_a_version(self) -> None:
        failures = []
        for dockerfile in collect_dockerfiles():
            relative = dockerfile.relative_to(_REPO_ROOT).as_posix()
            failures.extend(
                f"{relative}:{line}: pip install pins {package}=={version}"
                for line, package, version in pinned_installs(dockerfile)
            )

        self.assertFalse(
            failures,
            f"{len(failures)} exact pip pin(s) inside a Dockerfile. Dependabot "
            "does not read a version written into a build recipe, so it ages "
            "silently. Move the pin into a requirements.txt or pyproject.toml "
            "under the role's files/, stage that file into the build context "
            "and install it with `pip install -r`. A `--no-deps` group needs a "
            "requirements file of its own:\n\n"
            + "\n".join(f"  {f}" for f in failures),
        )


class TestPinnedInstallsDetector(unittest.TestCase):
    """Negative and positive controls for :func:`pinned_installs`.

    A scan that never fires passes every Dockerfile in the repository, so the
    detector itself needs a case that must fire and a set that must not.
    """

    FLAGGED: ClassVar[tuple[tuple[str, str], ...]] = (
        ("bare pin", "RUN pip install flask==3.0.0\n"),
        ("flags after install", "RUN pip install --no-cache-dir boto3==1.40.0\n"),
        ("flags before install", "RUN pip --no-cache-dir install boto3==1.40.0\n"),
        ("module invocation", "RUN python3 -m pip install foo==1.2.3\n"),
        ("venv pip", "RUN /venv/bin/pip install foo==1.2.3\n"),
        ("no-deps group", "RUN pip install --no-deps odoo-addon-fs_storage==19.0.1\n"),
        ("backslash continuation", "RUN pip install \\\n  foo==1.2.3 \\\n  bar\n"),
        ("second command in the chain", "RUN apt-get update && pip install foo==1.0\n"),
        ("extras bracket", "RUN pip install fsspec[s3]==2026.9.0\n"),
    )

    CLEAN: ClassVar[tuple[tuple[str, str], ...]] = (
        ("requirements file", "RUN pip install -r /opt/pip/requirements.txt\n"),
        ("apt version", "RUN apt-get install -y curl=7.88.1-10\n"),
        ("npm version", "RUN npm i left-pad@1.3.0\n"),
        (
            "apt after pip",
            "RUN pip install -r /r.txt \\\n && apt-get install -y c=7.1\n",
        ),
        ("shell after pip", "RUN pip install foo && \\\n    echo 'A==1' >> /etc/x\n"),
        ("whole-line comment", "# moved: pip install pytest==1.0\nFROM debian:13\n"),
        (
            "comment in a chain",
            "RUN pip install -r /r.txt \\\n # bar==2.0 is preinstalled\n && rm /r.txt\n",
        ),
        ("build argument", "RUN pip install 'pretix-oidc==${OIDC_VERSION}'\n"),
        ("jinja expression", "RUN pip install foo=={{ FOO_VERSION }}\n"),
        ("heredoc requirements", "RUN cat > /r.txt <<'EOF'\nfoo==1.2.3\nEOF\n"),
        (
            "marker on the pin",
            "RUN pip install flask==3.0.0  # nocheck: dockerfile-pip-pin\n",
        ),
        (
            "marker above the pin",
            "# nocheck: dockerfile-pip-pin\nRUN pip install flask==3.0.0\n",
        ),
    )

    def _scan(self, body: str) -> list[tuple[int, str, str]]:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Dockerfile"
            path.write_text(body, encoding="utf-8")
            return pinned_installs(path)

    def test_pins_inside_a_pip_install_are_reported(self) -> None:
        for name, body in self.FLAGGED:
            with self.subTest(name):
                self.assertTrue(self._scan(body), f"{name!r} should be reported")

    def test_legitimate_constructs_are_not_reported(self) -> None:
        for name, body in self.CLEAN:
            with self.subTest(name):
                self.assertEqual([], self._scan(body), f"{name!r} must not fire")


if __name__ == "__main__":
    unittest.main()
