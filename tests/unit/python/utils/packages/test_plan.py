import re
import unittest

from utils.packages.calls import STATE_ABSENT, STATE_PRESENT
from utils.packages.plan import build_plan
from utils.packages.schema import (
    SOURCE_AUR,
    SOURCE_BUILD,
    SOURCE_COPR,
    SOURCE_DOWNLOAD,
    SOURCE_FLATPAK,
    PackageSpec,
)
from utils.packages.sources import (
    AUR_BUILDER_USER,
    DOWNLOAD_CACHE_DIR,
    FLATPAK_COMMAND_DIR,
    FLATPAK_EXPORT_DIR,
    PACMAN_CONF,
)


def _only(plan, module):
    """Return the single call to *module*, failing when it is not unique."""
    calls = [call for call in plan if call.module == module]
    assert len(calls) == 1, f"{module} appears {len(calls)} times"
    return calls[0]


_DEB = {
    "url": "https://vendor.example/pool/editor_1.2.3_amd64.deb",
    "checksum": "sha256:" + "a" * 64,
}
_RPM = {
    "url": "https://vendor.example/pool/editor-1.2.3.el8.x86_64.rpm",
    "checksum": "sha256:" + "b" * 64,
}


class TestExternalFetchRetries(unittest.TestCase):
    """Every call that fetches over the network carries a retry policy, the
    distribution's own repositories included: their mirror pools degrade
    independently of whatever retries the package manager does internally."""

    def _retried(self, plan):
        return {call.module for call in plan if call.retry is not None}

    def test_the_aur_build_is_retried(self):
        plan = build_plan(
            PackageSpec(("nfs-ganesha",), source=SOURCE_AUR), STATE_PRESENT
        )
        self.assertEqual(
            self._retried(plan), {"kewlfft.aur.aur", "ansible.builtin.package"}
        )

    def test_the_build_command_is_retried(self):
        spec = PackageSpec(("tool",), source=SOURCE_BUILD, build={"command": "make"})
        self.assertEqual(
            self._retried(build_plan(spec, STATE_PRESENT)),
            {"ansible.builtin.command", "ansible.builtin.package"},
        )

    def test_enabling_a_copr_is_retried(self):
        spec = PackageSpec(("pkg",), source=SOURCE_COPR, repo={"copr": "user/proj"})
        self.assertEqual(
            self._retried(build_plan(spec, STATE_PRESENT)),
            {"community.general.copr", "ansible.builtin.package"},
        )

    def test_adding_a_ppa_is_retried(self):
        spec = PackageSpec(("pkg",), repo={"ppa": "ppa:x/y"})
        self.assertEqual(
            self._retried(build_plan(spec, STATE_PRESENT)),
            {"ansible.builtin.apt_repository", "ansible.builtin.package"},
        )

    def test_a_plain_repository_install_is_retried(self):
        plan = build_plan(PackageSpec(("git",)), STATE_PRESENT)
        self.assertEqual(self._retried(plan), {"ansible.builtin.package"})


def _modules(plan):
    return [call.module for call in plan]


class TestBuildPlan(unittest.TestCase):
    def test_plain_repo_is_a_single_call(self):
        plan = build_plan(PackageSpec(("git",)), STATE_PRESENT)
        self.assertEqual(_modules(plan), ["ansible.builtin.package"])
        self.assertEqual(plan[0].args["state"], STATE_PRESENT)

    def test_empty_names_produce_no_calls(self):
        self.assertEqual(build_plan(PackageSpec(()), STATE_PRESENT), [])

    def test_absent_never_needs_the_source(self):
        spec = PackageSpec(("nfs-ganesha",), source="aur")
        plan = build_plan(spec, STATE_ABSENT)
        self.assertEqual(_modules(plan), ["ansible.builtin.package"])
        self.assertEqual(plan[0].args["state"], STATE_ABSENT)

    def test_aur_bootstraps_a_build_user_then_builds(self):
        plan = build_plan(PackageSpec(("nfs-ganesha",), source="aur"), STATE_PRESENT)
        self.assertEqual(
            _modules(plan),
            [
                "ansible.builtin.package",
                "ansible.builtin.user",
                "ansible.builtin.lineinfile",
                "kewlfft.aur.aur",
            ],
        )
        self.assertEqual(plan[-1].become_user, AUR_BUILDER_USER)

    def test_copr_enables_before_installing(self):
        spec = PackageSpec(("foo",), source="copr", repo={"copr": "user/project"})
        plan = build_plan(spec, STATE_PRESENT)
        self.assertEqual(
            _modules(plan), ["community.general.copr", "ansible.builtin.package"]
        )

    def test_ppa_adds_the_repository_before_installing(self):
        spec = PackageSpec(("foo",), source="ppa", repo={"ppa": "ppa:user/foo"})
        plan = build_plan(spec, STATE_PRESENT)
        self.assertEqual(
            _modules(plan),
            ["ansible.builtin.apt_repository", "ansible.builtin.package"],
        )

    def test_copr_without_repo_raises(self):
        with self.assertRaises(ValueError):
            build_plan(PackageSpec(("foo",), source="copr"), STATE_PRESENT)

    def test_build_installs_depends_then_runs_the_command(self):
        spec = PackageSpec(
            ("foo",),
            source="build",
            build={
                "command": "make install",
                "depends": ["gcc"],
                "creates": "/usr/bin/foo",
            },
        )
        plan = build_plan(spec, STATE_PRESENT)
        self.assertEqual(
            _modules(plan), ["ansible.builtin.package", "ansible.builtin.command"]
        )
        self.assertEqual(plan[1].args["cmd"], "make install")

    def test_build_without_block_raises(self):
        with self.assertRaises(ValueError):
            build_plan(PackageSpec(("foo",), source="build"), STATE_PRESENT)

    def test_bootstrap_package_repo_installs_the_enabler_first(self):
        spec = PackageSpec(("micro",), repo={"bootstrap_package": "epel-release"})
        plan = build_plan(spec, STATE_PRESENT)
        self.assertEqual(plan[0].args["name"], ["epel-release"])
        self.assertEqual(plan[1].args["name"], ["micro"])

    def test_enable_existing_uses_dnf_with_the_repo(self):
        spec = PackageSpec(
            ("libntirpc",),
            repo={"enable_existing": "updates-testing", "state": "latest"},
        )
        plan = build_plan(spec, STATE_PRESENT)
        self.assertEqual(_modules(plan), ["ansible.builtin.dnf"])
        self.assertEqual(plan[0].args["enablerepo"], "updates-testing")

    def test_pacman_section_is_uncommented_before_the_install(self):
        spec = PackageSpec(("steam",), repo={"pacman_section": "multilib"})
        plan = build_plan(spec, STATE_PRESENT)
        self.assertEqual(
            _modules(plan), ["ansible.builtin.replace", "community.general.pacman"]
        )
        self.assertEqual(plan[0].args["path"], PACMAN_CONF)
        self.assertIn("multilib", plan[0].args["regexp"])
        self.assertTrue(plan[1].args["update_cache"])
        self.assertEqual(plan[1].args["name"], ["steam"])

    def test_pacman_section_regex_matches_the_stock_pacman_conf(self):
        spec = PackageSpec(("steam",), repo={"pacman_section": "multilib"})
        call = build_plan(spec, STATE_PRESENT)[0]
        stock = "#[multilib]\n#Include = /etc/pacman.d/mirrorlist\n"
        enabled = re.sub(
            call.args["regexp"],
            call.args["replace"].replace("\\n", "\n"),
            stock,
            flags=re.MULTILINE,
        )
        self.assertEqual(enabled, "[multilib]\nInclude = /etc/pacman.d/mirrorlist\n")
        self.assertEqual(
            re.sub(
                call.args["regexp"],
                call.args["replace"].replace("\\n", "\n"),
                enabled,
                flags=re.MULTILINE,
            ),
            enabled,
        )

    def test_externally_managed_repo_only_installs(self):
        spec = PackageSpec(("docker-ce",), repo={"managed_externally": "role does it"})
        plan = build_plan(spec, STATE_PRESENT)
        self.assertEqual(_modules(plan), ["ansible.builtin.package"])

    def test_full_repo_definition_is_rendered_first(self):
        spec = PackageSpec(
            ("nfs-ganesha",),
            repo={
                "name": "sig",
                "description": "SIG",
                "baseurl": "https://example/",
                "gpgkey": "https://example/key",
            },
        )
        plan = build_plan(spec, STATE_PRESENT)
        self.assertEqual(
            _modules(plan),
            ["ansible.builtin.yum_repository", "ansible.builtin.package"],
        )


class TestDownloadSource(unittest.TestCase):
    """A vendor artefact is fetched against its pin and installed from disk,
    so what the package manager receives is the file the registry describes."""

    def test_the_deb_is_fetched_with_its_checksum_then_installed(self):
        plan = build_plan(
            PackageSpec(("editor",), source=SOURCE_DOWNLOAD, download=_DEB),
            STATE_PRESENT,
        )
        self.assertEqual(
            _modules(plan),
            [
                "ansible.builtin.package",
                "ansible.builtin.file",
                "ansible.builtin.get_url",
                "ansible.builtin.apt",
                "ansible.builtin.package",
            ],
        )
        tools, cache, fetch, install, confirm = plan
        self.assertEqual(tools.args["name"], ["xz-utils"])
        self.assertEqual(cache.args["path"], DOWNLOAD_CACHE_DIR)
        self.assertEqual(cache.args["owner"], "root")
        self.assertEqual(confirm.args["name"], ["editor"])
        self.assertEqual(fetch.args["url"], _DEB["url"])
        self.assertEqual(fetch.args["checksum"], _DEB["checksum"])
        self.assertEqual(
            fetch.args["dest"], f"{DOWNLOAD_CACHE_DIR}/editor_1.2.3_amd64.deb"
        )
        self.assertEqual(install.args["deb"], fetch.args["dest"])

    def test_the_rpm_is_installed_from_the_fetched_path(self):
        plan = build_plan(
            PackageSpec(("editor",), source=SOURCE_DOWNLOAD, download=_RPM),
            STATE_PRESENT,
        )
        self.assertEqual(
            _modules(plan),
            [
                "ansible.builtin.file",
                "ansible.builtin.get_url",
                "ansible.builtin.dnf",
                "ansible.builtin.package",
            ],
        )
        _cache, fetch, install, confirm = plan
        self.assertEqual(install.args["name"], [fetch.args["dest"]])
        self.assertEqual(install.args["state"], STATE_PRESENT)
        self.assertEqual(confirm.args["name"], ["editor"])

    def test_an_unsupported_artefact_is_refused(self):
        spec = PackageSpec(
            ("editor",),
            source=SOURCE_DOWNLOAD,
            download={"url": "https://vendor.example/editor.AppImage", "checksum": "x"},
        )
        with self.assertRaises(ValueError) as caught:
            build_plan(spec, STATE_PRESENT)
        self.assertIn(".AppImage", str(caught.exception))

    def test_a_query_string_does_not_hide_the_artefact_type(self):
        spec = PackageSpec(
            ("editor",),
            source=SOURCE_DOWNLOAD,
            download={**_DEB, "url": _DEB["url"] + "?token=abc"},
        )
        plan = build_plan(spec, STATE_PRESENT)
        self.assertIn("ansible.builtin.apt", _modules(plan))
        fetch = _only(plan, "ansible.builtin.get_url")
        self.assertEqual(
            fetch.args["dest"], f"{DOWNLOAD_CACHE_DIR}/editor_1.2.3_amd64.deb"
        )

    def test_the_source_without_its_block_is_refused(self):
        spec = PackageSpec(("editor",), source=SOURCE_DOWNLOAD)
        with self.assertRaises(ValueError):
            build_plan(spec, STATE_PRESENT)

    def test_the_fetch_is_retried(self):
        plan = build_plan(
            PackageSpec(("editor",), source=SOURCE_DOWNLOAD, download=_DEB),
            STATE_PRESENT,
        )
        self.assertIsNotNone(_only(plan, "ansible.builtin.get_url").retry)

    def test_removal_goes_through_the_host_manager(self):
        plan = build_plan(
            PackageSpec(("editor",), source=SOURCE_DOWNLOAD, download=_DEB),
            STATE_ABSENT,
        )
        self.assertEqual(_modules(plan), ["ansible.builtin.package"])
        self.assertEqual(plan[0].args["name"], ["editor"])


class TestFlatpakSource(unittest.TestCase):
    """A Flatpak id is installed from a remote and exposed under the name the
    role actually invokes."""

    def test_the_runtime_and_remote_come_before_the_application(self):
        spec = PackageSpec(("org.blender.Blender",), source=SOURCE_FLATPAK)
        self.assertEqual(
            _modules(build_plan(spec, STATE_PRESENT)),
            [
                "ansible.builtin.package",
                "community.general.flatpak_remote",
                "community.general.flatpak",
            ],
        )

    def test_a_declared_command_is_linked_onto_the_path(self):
        spec = PackageSpec(
            ("org.blender.Blender",),
            source=SOURCE_FLATPAK,
            flatpak={"command": "blender"},
        )
        link = build_plan(spec, STATE_PRESENT)[-1]
        self.assertEqual(link.module, "ansible.builtin.file")
        self.assertEqual(link.args["state"], "link")
        self.assertEqual(link.args["dest"], f"{FLATPAK_COMMAND_DIR}/blender")
        self.assertEqual(link.args["src"], f"{FLATPAK_EXPORT_DIR}/org.blender.Blender")

    def test_without_a_command_nothing_is_linked(self):
        spec = PackageSpec(("org.blender.Blender",), source=SOURCE_FLATPAK)
        self.assertNotIn(
            "ansible.builtin.file", _modules(build_plan(spec, STATE_PRESENT))
        )

    def test_the_remote_and_the_install_are_retried(self):
        spec = PackageSpec(("org.blender.Blender",), source=SOURCE_FLATPAK)
        retried = {
            call.module for call in build_plan(spec, STATE_PRESENT) if call.retry
        }
        self.assertEqual(
            retried,
            {
                "ansible.builtin.package",
                "community.general.flatpak_remote",
                "community.general.flatpak",
            },
        )

    def test_removal_goes_through_the_host_manager(self):
        spec = PackageSpec(("org.blender.Blender",), source=SOURCE_FLATPAK)
        self.assertEqual(
            _modules(build_plan(spec, STATE_ABSENT)), ["ansible.builtin.package"]
        )


if __name__ == "__main__":
    unittest.main()
