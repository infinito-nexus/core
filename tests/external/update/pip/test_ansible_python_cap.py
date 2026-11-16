"""Check the Python cap in ``requires-python`` against the newest ``ansible`` release.

``pyproject.toml`` caps the supported Python (``>=3.11,<3.15``) because the
unpinned ``ansible`` dependency resolves to an ansible-core that cannot run on
the next minor: ansible-core 2.21 calls ``dataclasses._is_type``, which Python
3.15 removed. No updater touches ``requires-python``, so the cap needs a
watcher.

This is external because the answer lives on PyPI: the newest ``ansible``
release, the ansible-core range it requires, and the Python classifiers of the
newest ansible-core inside that range. It contacts only the JSON API on
``pypi.org``.

- The test fails when the cap allows a Python minor that this ansible-core
  does not support, because the bootstrap would then pick an interpreter the
  deploy cannot run on.
- It only warns when ansible-core supports a newer minor than the cap, because
  raising the cap needs a test run on every workspace distribution first.
- It warns and passes when PyPI does not answer.
"""

from __future__ import annotations

import http.client
import json
import re
import unittest
import urllib.error
import urllib.request

from packaging.requirements import Requirement
from packaging.version import InvalidVersion, Version

from utils.annotations.message import warning
from utils.requires_python import requires_python, supported_minors

from . import PROJECT_ROOT

PYPI_API = "https://pypi.org/pypi/{}"
TIMEOUT_SECONDS = 15
USER_AGENT = "infinito-nexus python cap check"
CLASSIFIER = re.compile(r"^Programming Language :: Python :: 3\.(\d+)$")


class PyPIUnavailableError(Exception):
    """PyPI did not answer with usable JSON."""


def pypi_json(path: str) -> dict:
    """Return one PyPI JSON API document.

    Args:
        path: the part after ``/pypi/``, e.g. ``ansible/json``.

    Raises:
        PyPIUnavailableError: the request failed or returned no JSON.
    """
    request = urllib.request.Request(  # noqa: S310 - fixed https PyPI origin, path built from literal package names
        PYPI_API.format(path), headers={"User-Agent": USER_AGENT}
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310 - fixed https PyPI origin, path built from literal package names
            return json.loads(response.read().decode())
    except (
        urllib.error.URLError,
        OSError,
        http.client.HTTPException,
        json.JSONDecodeError,
    ) as exc:
        raise PyPIUnavailableError(f"{path}: {exc}") from exc


def declared_cap() -> int:
    """Return the highest Python 3 minor ``requires-python`` admits."""
    return max(supported_minors(requires_python(PROJECT_ROOT)))


def core_requirement(ansible: dict) -> Requirement:
    """Return the ansible-core requirement of one ``ansible`` release document."""
    for raw in ansible["info"].get("requires_dist") or []:
        requirement = Requirement(raw)
        if requirement.name == "ansible-core" and requirement.marker is None:
            return requirement
    raise AssertionError(
        f"ansible {ansible['info']['version']} declares no ansible-core requirement"
    )


def newest_matching(releases: dict, requirement: Requirement) -> Version:
    """Return the newest non-yanked final release that satisfies ``requirement``.

    Args:
        releases: the ``releases`` map of a PyPI project document.
        requirement: the ansible-core requirement of the ``ansible`` release.
    """
    candidates = []
    for raw, files in releases.items():
        try:
            version = Version(raw)
        except InvalidVersion:
            continue
        if version.is_prerelease or not any(not f.get("yanked") for f in files):
            continue
        if version in requirement.specifier:
            candidates.append(version)
    if not candidates:
        raise AssertionError(f"no ansible-core release satisfies {requirement}")
    return max(candidates)


def highest_classified_minor(core: dict) -> int:
    """Return the highest Python 3 minor an ansible-core release classifies."""
    minors = [
        int(match[1])
        for classifier in core["info"].get("classifiers") or []
        if (match := CLASSIFIER.match(classifier))
    ]
    if not minors:
        raise AssertionError(
            f"ansible-core {core['info']['version']} lists no Python 3 classifier"
        )
    return max(minors)


def verdict(cap: int, supported: int) -> str | None:
    """Return the failure for a cap above ``supported``, ``None`` otherwise."""
    if cap > supported:
        return (
            f"requires-python admits Python 3.{cap}, but the ansible-core the "
            f"newest ansible pulls in supports up to 3.{supported}; lower the "
            f"upper bound to <3.{supported + 1}"
        )
    return None


class TestAnsiblePythonCap(unittest.TestCase):
    def test_the_cap_matches_what_the_newest_ansible_runs_on(self) -> None:
        try:
            ansible = pypi_json("ansible/json")
            requirement = core_requirement(ansible)
            core_version = newest_matching(
                pypi_json("ansible-core/json")["releases"], requirement
            )
            core = pypi_json(f"ansible-core/{core_version}/json")
        except PyPIUnavailableError as exc:
            warning(f"PyPI did not answer, cap not checked: {exc}", title="Python cap")
            return
        cap = declared_cap()
        supported = highest_classified_minor(core)
        failure = verdict(cap, supported)
        self.assertIsNone(failure, failure)
        if supported > cap:
            warning(
                f"ansible {ansible['info']['version']} pulls ansible-core "
                f"{core_version}, which supports Python 3.{supported}; "
                f"requires-python still stops at 3.{cap}. Raise it to "
                f"<3.{supported + 1} after a workspace run on every distribution.",
                title="Python cap can be raised",
                file="pyproject.toml",
            )


class TestVerdict(unittest.TestCase):
    def test_a_cap_above_the_supported_minor_fails(self) -> None:
        self.assertIn("lower the upper bound to <3.15", verdict(15, 14))

    def test_a_cap_at_or_below_the_supported_minor_passes(self) -> None:
        self.assertEqual((verdict(14, 14), verdict(14, 15)), (None, None))

    def test_the_newest_satisfying_final_release_is_chosen(self) -> None:
        releases = {
            "2.21.5": [{"yanked": False}],
            "2.21.6": [{"yanked": False}],
            "2.21.7": [{"yanked": True}],
            "2.22.0": [{"yanked": False}],
            "2.21.8rc1": [{"yanked": False}],
        }
        self.assertEqual(
            newest_matching(releases, Requirement("ansible-core~=2.21.5")),
            Version("2.21.6"),
        )

    def test_the_highest_python_classifier_wins(self) -> None:
        core = {
            "info": {
                "version": "2.21.6",
                "classifiers": [
                    "Programming Language :: Python :: 3",
                    "Programming Language :: Python :: 3.12",
                    "Programming Language :: Python :: 3.14",
                    "Programming Language :: Python :: 3.13",
                ],
            }
        }
        self.assertEqual(highest_classified_minor(core), 14)


if __name__ == "__main__":
    unittest.main()
