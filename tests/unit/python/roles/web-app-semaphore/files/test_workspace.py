from __future__ import annotations

import json
import tempfile
import unittest
import unittest.mock as mock
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from utils.cache.files import read_text

from ._semaphore_fake import CHANGELOG, PYTHON_DIR, WORKSPACE_ID, load_workspace


def apply_env(source, **overrides):
    """Args:
    source: a core tree with a changelog.
    overrides: inputs to set, None to leave one out.

    Returns:
        The environment of an ``apply`` without servers.
    """
    env = {
        "WORKSPACE": WORKSPACE_ID,
        "WORKSPACE_ACTION": "apply",
        "WORKSPACE_CORE_VERSION": "latest",
        "WORKSPACE_CORE_FLOOR": "17.0.0",
        "WORKSPACE_TARGETS": "",
        "WORKSPACE_PLATFORM_TOKENS": "false",
        "INFINITO_SRC_DIR": str(source),
        **overrides,
    }
    return {name: value for name, value in env.items() if value is not None}


def accepts_empty_targets(module, source):
    """Args:
    module: :func:`load_workspace`, possibly patched.
    source: a core tree with a changelog.

    Returns:
        True when ``apply`` takes an empty ``WORKSPACE_TARGETS`` as a workspace
        without servers.
    """
    try:
        variables = module.operation(apply_env(source), "/nonexistent/result.json")
    except module.RefusalError:
        return False
    return variables["WORKSPACE_TARGETS"] == []


class WorkspaceOperationTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.src = Path(scratch.name)
        (self.src / "CHANGELOG.md").write_text(CHANGELOG, encoding="utf-8")

    def test_operation_takes_an_empty_target_list_as_no_servers(self):
        self.assertTrue(accepts_empty_targets(load_workspace(), self.src))

    def test_negative_control_a_refused_empty_list_fails_the_check(self):
        module = load_workspace()
        parse = module.parse_targets

        def refusing(value):
            if not value:
                raise module.RefusalError("WORKSPACE_TARGETS is empty")
            return parse(value)

        with mock.patch.object(module, "parse_targets", refusing):
            self.assertFalse(accepts_empty_targets(module, self.src))


class PlatformTokensTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.src = Path(scratch.name)
        (self.src / "CHANGELOG.md").write_text(CHANGELOG, encoding="utf-8")
        self.module = load_workspace()

    def operation(self, **overrides):
        return self.module.operation(
            apply_env(self.src, **overrides), "/nonexistent/result.json"
        )

    def test_apply_hands_the_store_switch_to_the_playbook_as_a_boolean(self):
        for value, expected in (("true", True), ("false", False)):
            with self.subTest(value=value):
                handed = self.operation(WORKSPACE_PLATFORM_TOKENS=value)
                self.assertIs(handed["WORKSPACE_PLATFORM_TOKENS"], expected)

    def test_negative_control_an_apply_without_the_switch_is_refused(self):
        with self.assertRaisesRegex(
            self.module.RefusalError, "WORKSPACE_PLATFORM_TOKENS None is neither"
        ):
            self.operation(WORKSPACE_PLATFORM_TOKENS=None)

    def test_negative_control_a_non_boolean_switch_is_refused(self):
        for value in ("", "True", "1", "yes", "on"):
            with (
                self.subTest(value=value),
                self.assertRaisesRegex(
                    self.module.RefusalError, "is neither true nor false"
                ),
            ):
                self.operation(WORKSPACE_PLATFORM_TOKENS=value)

    def test_destroy_takes_no_switch(self):
        env = {
            "WORKSPACE": WORKSPACE_ID,
            "WORKSPACE_ACTION": "destroy",
            "WORKSPACE_PLATFORM_TOKENS": "true",
        }
        with self.assertRaisesRegex(
            self.module.RefusalError,
            "WORKSPACE_PLATFORM_TOKENS is not taken by destroy",
        ):
            self.module.operation(env, "/nonexistent/result.json")


RELEASED = ["17.0.0", "16.2.0"]
OWN_TAG = "ci-0123abcd"
OWN_BUILD = f"registry.local:5000/infinito-nexus/core:{OWN_TAG}"
OWN_VERSION = "17.1.0"
INTERFACE = PYTHON_DIR.parent / "opentofu" / "interface.json"
OWN_SELECTION = 'value in (LATEST, own_build.rpartition(":")[2])'
TAG_SELECTION = 'value == own_build.rpartition(":")[2]'
PREDATES = "predates the workspace runner"
FROM_FLOOR = "which ships from 17.0.0 on"
NO_RELEASE = "which ships in no release yet"
FLOOR_FILTER = "if floor and release_key(v) >= release_key(floor)"
UNFLOORED = "if floor"


def unfloored_workspace(case):
    """Args:
    case: the running test, which asserts the floor filter is spelled once.

    Returns:
        A copy of ``workspace.py`` whose ``core_version`` keeps the floor
        switch but drops the comparison with the floor.
    """
    source = read_text(str(PYTHON_DIR / "workspace.py"))
    case.assertEqual(source.count(FLOOR_FILTER), 1)
    return workspace_copy(
        source.replace(FLOOR_FILTER, UNFLOORED), read_text(str(INTERFACE))
    )


def resolution(module, value, floor, own_build):
    """Args:
    module: :func:`load_workspace`, possibly patched.
    value: ``WORKSPACE_CORE_VERSION``.
    floor: ``WORKSPACE_CORE_FLOOR``.
    own_build: ``WORKSPACE_OWN_BUILD``, empty as on production.

    Returns:
        ``(version, base)`` with ``RELEASED`` released and ``OWN_VERSION``
        declared by the own build, or the refusal.
    """
    own_version = OWN_VERSION if own_build else ""
    try:
        return module.core_version(value, RELEASED, floor, own_build, own_version)
    except module.RefusalError as refusal:
        return str(refusal)


class CoreVersionTests(unittest.TestCase):
    def setUp(self):
        self.module = load_workspace()

    def test_the_floor_admits_the_releases_at_or_above_it_alone(self):
        self.assertEqual(
            resolution(self.module, "17.0.0", "17.0.0", ""), ("17.0.0", "")
        )
        self.assertEqual(
            resolution(self.module, "16.2.0", "17.0.0", ""),
            f"WORKSPACE_CORE_VERSION 16.2.0 {PREDATES}, {FROM_FLOOR}",
        )
        self.assertEqual(
            resolution(self.module, "17.0.0", "", ""),
            f"WORKSPACE_CORE_VERSION 17.0.0 {PREDATES}, {NO_RELEASE}",
        )

    def test_negative_control_an_unfloored_check_admits_an_older_release(self):
        planted = unfloored_workspace(self)
        self.assertEqual(
            resolution(self.module, "16.2.0", "17.0.0", ""),
            f"WORKSPACE_CORE_VERSION 16.2.0 {PREDATES}, {FROM_FLOOR}",
        )
        self.assertEqual(resolution(planted, "16.2.0", "17.0.0", ""), ("16.2.0", ""))

    def test_latest_is_the_newest_release_at_or_above_the_floor(self):
        self.assertEqual(
            resolution(self.module, "latest", "16.2.0", ""), ("17.0.0", "")
        )
        cases = (("17.1.0", "which ships from 17.1.0 on"), ("", NO_RELEASE))
        for floor, shipped in cases:
            with self.subTest(floor=floor):
                self.assertEqual(
                    resolution(self.module, "latest", floor, ""),
                    "WORKSPACE_CORE_VERSION latest finds no release of the workspace "
                    f"runner, {shipped}",
                )

    def test_negative_control_an_unfloored_latest_picks_below_the_floor(self):
        planted = unfloored_workspace(self)
        self.assertEqual(
            resolution(self.module, "latest", "17.1.0", ""),
            "WORKSPACE_CORE_VERSION latest finds no release of the workspace "
            "runner, which ships from 17.1.0 on",
        )
        self.assertEqual(resolution(planted, "latest", "17.1.0", ""), ("17.0.0", ""))

    def test_a_dev_or_ci_deploy_admits_its_own_build_by_its_tag(self):
        self.assertEqual(
            resolution(self.module, OWN_TAG, "", OWN_BUILD), (OWN_VERSION, OWN_BUILD)
        )

    def test_latest_on_a_dev_or_ci_deploy_is_its_own_build(self):
        for floor in ("", "16.2.0"):
            with self.subTest(floor=floor):
                self.assertEqual(
                    resolution(self.module, "latest", floor, OWN_BUILD),
                    (OWN_VERSION, OWN_BUILD),
                )

    def test_negative_control_latest_without_the_own_build_branch_is_refused(self):
        source = read_text(str(PYTHON_DIR / "workspace.py"))
        self.assertEqual(source.count(OWN_SELECTION), 1)
        planted = workspace_copy(
            source.replace(OWN_SELECTION, TAG_SELECTION), read_text(str(INTERFACE))
        )
        self.assertEqual(
            resolution(self.module, "latest", "", OWN_BUILD), (OWN_VERSION, OWN_BUILD)
        )
        self.assertEqual(
            resolution(planted, "latest", "", OWN_BUILD),
            "WORKSPACE_CORE_VERSION latest finds no release of the workspace "
            f"runner, {NO_RELEASE}",
        )

    def test_production_refuses_the_tag_of_an_own_build(self):
        self.assertEqual(
            resolution(self.module, OWN_TAG, "", ""),
            f"WORKSPACE_CORE_VERSION {OWN_TAG!r} is neither latest nor a version "
            "like 17.0.0",
        )

    def test_negative_control_another_tag_is_no_own_build(self):
        self.assertEqual(
            resolution(self.module, "ci-ffffffff", "", OWN_BUILD),
            "WORKSPACE_CORE_VERSION 'ci-ffffffff' is neither latest nor a version "
            "like 17.0.0",
        )

    def test_a_malformed_floor_or_own_build_version_is_refused(self):
        self.assertEqual(
            resolution(self.module, "17.0.0", "v17.0.0", ""),
            "WORKSPACE_CORE_FLOOR 'v17.0.0' is no version like 17.0.0",
        )
        for value in (OWN_TAG, "latest"):
            with (
                self.subTest(value=value),
                self.assertRaisesRegex(
                    self.module.RefusalError,
                    "WORKSPACE_OWN_BUILD_VERSION '' is no version like 17.0.0",
                ),
            ):
                self.module.core_version(value, RELEASED, "", OWN_BUILD, "")


def workspace_copy(source, interface):
    """Args:
    source: the text of a ``workspace.py``, possibly planted.
    interface: the text of the ``opentofu/interface.json`` beside it.

    Returns:
        That ``workspace.py`` loaded from ``python/`` beside that
        ``opentofu/interface.json``.
    """
    with tempfile.TemporaryDirectory() as scratch:
        root = Path(scratch)
        (root / "python").mkdir()
        (root / "opentofu").mkdir()
        (root / "python" / "workspace.py").write_text(source, "utf-8")
        (root / "opentofu" / "interface.json").write_text(interface, "utf-8")
        spec = spec_from_file_location(
            "semaphore_workspace_copy", str(root / "python" / "workspace.py")
        )
        module = module_from_spec(spec)
        spec.loader.exec_module(module)
        return module


def hostname_pattern_beside(interface_pattern):
    """Args:
    interface_pattern: the ``$defs.host_name`` pattern of a planted
        ``interface.json``.

    Returns:
        The ``HOSTNAME`` pattern a copy of ``workspace.py`` compiles when it sits
        in ``python/`` beside that ``opentofu/interface.json``.
    """
    interface = json.dumps({"$defs": {"host_name": {"pattern": interface_pattern}}})
    source = read_text(str(PYTHON_DIR / "workspace.py"))
    return workspace_copy(source, interface).HOSTNAME.pattern


class HostNamePatternTests(unittest.TestCase):
    def test_targets_take_the_host_name_pattern_of_the_interface(self):
        interface = json.loads(
            read_text(str(PYTHON_DIR.parent / "opentofu" / "interface.json"))
        )
        self.assertEqual(
            load_workspace().HOSTNAME.pattern,
            interface["$defs"]["host_name"]["pattern"],
        )

    def test_a_planted_interface_pattern_reaches_the_targets(self):
        self.assertEqual(hostname_pattern_beside("^planted$"), "^planted$")


if __name__ == "__main__":
    unittest.main()
