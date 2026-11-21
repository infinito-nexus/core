from __future__ import annotations

import tempfile
import unittest
import unittest.mock as mock
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from ansible.parsing.dataloader import DataLoader
from ansible.plugins.loader import filter_loader, lookup_loader
from ansible.plugins.lookup import LookupBase
from ansible.template import Templar, trust_as_template

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

from .files._semaphore_fake import load_workspace

ROLE = PROJECT_ROOT / "roles" / "web-app-semaphore"
VARS = ROLE / ROLE_FILE_VARS_MAIN
FILTERS = ROLE / "filter_plugins" / "semaphore_workspace.py"
filter_loader.add_directory(str(FILTERS.parent))
CHANGELOG = (
    "# Changelog\n\n## [17.2.0] - 2027-02-01\n\n## [17.1.0] - 2027-01-01\n\n"
    "## [17.0.0] - 2026-11-08\n"
)
NEWER_CONTROLLER = f"# Changelog\n\n## [17.3.0] - 2027-03-01\n\n{CHANGELOG[13:]}"
CONTROLLER_RELEASES = (
    "{{ (lookup('file', lookup('path_absolute', 'CHANGELOG.md'))"
    " | regex_findall('^## [[]([0-9]+[.][0-9]+[.][0-9]+)[]]', multiline=True)"
    " | select('version', SEMAPHORE_WORKSPACE_CORE_FLOOR, '>=') | list)"
    " if SEMAPHORE_WORKSPACE_CORE_FLOOR else [] }}"
)
FLOORS = ("", "17.0.0", "17.1.0", "18.0.0")
CHANGELOG_READ = [
    "container",
    "run",
    "--rm",
    "--pull",
    "never",
    "--network",
    "none",
    "--entrypoint",
    "cat",
    "{{ SEMAPHORE_RUNNER_IMAGE }}",
    "{{ SEMAPHORE_RUNNER_CHANGELOG_FILE }}",
]
SOFTWARE_IMAGE = "slot/debian"
OWN_TAG = "ci-0123abcd"
OWN_BUILD = f"{SOFTWARE_IMAGE}:{OWN_TAG}"
OWN_VERSION = "17.3.0"
TEST_RUNTIMES = ("dev", "act", "github")
NAMES = (
    "SEMAPHORE_WORKSPACE_OWN_BUILD",
    "SEMAPHORE_WORKSPACE_OWN_BUILD_VERSION",
    "SEMAPHORE_WORKSPACE_CORE_PICKS",
)
OWN_PICKS = {
    "SEMAPHORE_WORKSPACE_OWN_BUILD": OWN_BUILD,
    "SEMAPHORE_WORKSPACE_OWN_BUILD_VERSION": OWN_VERSION,
    "SEMAPHORE_WORKSPACE_CORE_PICKS": [[OWN_TAG, OWN_VERSION]],
}
UNGATED = "{{ SOFTWARE_IMAGE ~ ':' ~ SOFTWARE_IMAGE_TAG }}"
UNFLOORED = (
    "{{ lookup('file', lookup('path_absolute', 'CHANGELOG.md'))"
    " | regex_findall('^## [[]([0-9]+[.][0-9]+[.][0-9]+)[]]', multiline=True) }}"
)


class _Stub(LookupBase):
    def __init__(self, answer):
        super().__init__()
        self._answer = answer

    def run(self, terms, variables=None, **kwargs):
        return [self._answer(*terms)]


def declared_vars():
    """Returns:
    The role vars as ``vars/main.yml`` declares them, trusted as templates.
    """
    return DataLoader().load_from_file(str(VARS), trusted_as_template=True)


def resolve(runtime, floor, planted, controller=CHANGELOG, names=NAMES):
    """Args:
    runtime: ``RUNTIME`` of the deploy.
    floor: ``SEMAPHORE_WORKSPACE_CORE_FLOOR``.
    planted: role vars that replace the ones ``vars/main.yml`` declares.
    controller: the ``CHANGELOG.md`` of the controller's checkout.
    names: the role vars to resolve.

    Returns:
        ``{name: value}`` for every name in ``names`` of a deploy that runs
        ``OWN_BUILD`` on a checkout that declares ``OWN_VERSION``, its
        platform runner image holding ``CHANGELOG``.
    """
    declared = declared_vars()
    facts = {
        "RUNTIME": runtime,
        "SEMAPHORE_DEPLOY_ENABLED": True,
        "SEMAPHORE_WORKSPACE_CORE_FLOOR": floor,
        "SOFTWARE_IMAGE": SOFTWARE_IMAGE,
        "SOFTWARE_IMAGE_TAG": OWN_TAG,
        "application_id": "web-app-semaphore",
        "semaphore_runner_changelog": {"rc": 0, "stdout": CHANGELOG},
    }
    trusted = {name: trust_as_template(value) for name, value in planted.items()}
    templar = Templar(loader=DataLoader(), variables={**declared, **facts, **trusted})
    stubs = {
        "config": _Stub(lambda *_terms: True),
        "file": _Stub(lambda _path: controller),
        "path_absolute": _Stub(lambda path: path),
        "version": _Stub(lambda: OWN_VERSION),
    }
    real_get = lookup_loader.get

    def get(name, *args, **kwargs):
        if name in stubs:
            return stubs[name]
        return real_get(name, *args, **kwargs)

    with mock.patch.object(lookup_loader, "get", side_effect=get):
        return {name: templar.template({**declared, **trusted}[name]) for name in names}


def accepted(floor):
    """Args:
    floor: ``WORKSPACE_CORE_FLOOR``.

    Returns:
        Every release ``workspace.py`` admits on a platform runner whose core
        tree holds ``CHANGELOG``, newest first.
    """
    module = load_workspace()
    with tempfile.TemporaryDirectory() as scratch:
        (Path(scratch) / "CHANGELOG.md").write_text(CHANGELOG, encoding="utf-8")
        released = module.released_versions(scratch)
    admitted = []
    for version in released:
        try:
            module.core_version(version, released, floor, "", "")
        except module.RefusalError:
            continue
        admitted.append(version)
    return admitted


def spec_releases(floor, planted, controller):
    """Args:
    floor: ``SEMAPHORE_WORKSPACE_CORE_FLOOR``.
    planted: role vars that replace the ones ``vars/main.yml`` declares.
    controller: the ``CHANGELOG.md`` of the controller's checkout.

    Returns:
        ``SEMAPHORE_WORKSPACE_CORE_RELEASES``, the releases the specs pick from.
    """
    names = ("SEMAPHORE_WORKSPACE_CORE_RELEASES",)
    return list(resolve("dev", floor, planted, controller, names)[names[0]])


class TestWorkspaceCorePicks(unittest.TestCase):
    def test_a_dev_or_ci_deploy_hands_the_workspaces_its_own_build(self):
        for runtime in TEST_RUNTIMES:
            with self.subTest(runtime=runtime):
                self.assertEqual(resolve(runtime, "", {}), OWN_PICKS)

    def test_production_hands_the_workspaces_no_own_build(self):
        self.assertEqual(
            resolve("host", "", {}),
            {
                "SEMAPHORE_WORKSPACE_OWN_BUILD": "",
                "SEMAPHORE_WORKSPACE_OWN_BUILD_VERSION": "",
                "SEMAPHORE_WORKSPACE_CORE_PICKS": [],
            },
        )

    def test_negative_control_an_ungated_own_build_reaches_production(self):
        self.assertNotEqual(declared_vars()["SEMAPHORE_WORKSPACE_OWN_BUILD"], UNGATED)
        planted = {"SEMAPHORE_WORKSPACE_OWN_BUILD": UNGATED}
        self.assertEqual(resolve("host", "", {})["SEMAPHORE_WORKSPACE_OWN_BUILD"], "")
        self.assertEqual(resolve("host", "", planted), OWN_PICKS)

    def test_the_specs_pick_the_two_newest_releases_at_or_above_the_floor(self):
        picks = resolve("dev", "17.1.0", {})["SEMAPHORE_WORKSPACE_CORE_PICKS"]
        self.assertEqual(picks, [["17.2.0", "17.2.0"], ["17.1.0", "17.1.0"]])

    def test_the_specs_pick_the_own_build_below_two_releases_at_the_floor(self):
        for floor in ("", "17.2.0", "18.0.0"):
            with self.subTest(floor=floor):
                self.assertEqual(resolve("dev", floor, {}), OWN_PICKS)

    def test_negative_control_picks_without_the_floor_take_older_releases(self):
        self.assertNotEqual(
            declared_vars()["SEMAPHORE_WORKSPACE_CORE_RELEASES"], UNFLOORED
        )
        planted = {"SEMAPHORE_WORKSPACE_CORE_RELEASES": UNFLOORED}
        real = resolve("dev", "17.2.0", {})["SEMAPHORE_WORKSPACE_CORE_PICKS"]
        self.assertEqual(real, [[OWN_TAG, OWN_VERSION]])
        picks = resolve("dev", "17.2.0", planted)["SEMAPHORE_WORKSPACE_CORE_PICKS"]
        self.assertEqual(picks, [["17.2.0", "17.2.0"], ["17.1.0", "17.1.0"]])

    def test_the_specs_pick_from_the_releases_the_runner_image_accepts(self):
        for floor in FLOORS:
            with self.subTest(floor=floor):
                self.assertEqual(
                    spec_releases(floor, {}, NEWER_CONTROLLER), accepted(floor)
                )

    def test_negative_control_a_newer_controller_changelog_is_caught(self):
        self.assertNotEqual(
            declared_vars()["SEMAPHORE_WORKSPACE_CORE_RELEASES"], CONTROLLER_RELEASES
        )
        planted = {"SEMAPHORE_WORKSPACE_CORE_RELEASES": CONTROLLER_RELEASES}
        picked = spec_releases("17.0.0", planted, NEWER_CONTROLLER)
        self.assertIn("17.3.0", picked)
        self.assertNotEqual(picked, accepted("17.0.0"))

    def test_the_deploy_reads_the_changelog_out_of_the_runner_image(self):
        tasks = load_yaml_str(read_text(str(ROLE / "tasks" / "00_core.yml")))
        read = next(
            task
            for task in tasks
            if task.get("register") == "semaphore_runner_changelog"
        )
        self.assertEqual(read["ansible.builtin.command"]["argv"], CHANGELOG_READ)
        self.assertEqual(read["environment"], {"CA_CONTAINER_ENABLED": "0"})
        self.assertIn("rc != 0", read["failed_when"])
        self.assertIn("length == 0", read["failed_when"])
        self.assertIn(
            f'"${{INFINITO_SRC_DIR}}/CHANGELOG.md" '
            f"{declared_vars()['SEMAPHORE_RUNNER_CHANGELOG_FILE']}",
            read_text(str(ROLE / "files" / "runner" / "Dockerfile")),
        )

    def test_an_empty_changelog_fails_loudly(self):
        spec = spec_from_file_location("semaphore_workspace_filters", str(FILTERS))
        module = module_from_spec(spec)
        spec.loader.exec_module(module)
        with self.assertRaisesRegex(ValueError, "empty CHANGELOG.md"):
            module.semaphore_workspace_releases(" \n", "17.0.0")

    def test_the_workspaces_environment_carries_the_floor_and_the_own_build(self):
        declared = declared_vars()
        self.assertEqual(declared["SEMAPHORE_WORKSPACE_CORE_FLOOR"], "")
        workspaces = declared["SEMAPHORE_WORKSPACES_VARIABLES"]
        for name in ("CORE_FLOOR", "OWN_BUILD", "OWN_BUILD_VERSION"):
            with self.subTest(name=name):
                self.assertEqual(
                    workspaces[f"WORKSPACE_{name}"],
                    f"{{{{ SEMAPHORE_WORKSPACE_{name} }}}}",
                )


if __name__ == "__main__":
    unittest.main()
