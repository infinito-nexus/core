import re
import unittest

from utils.packages.plan import (
    AUR_BUILDER_USER,
    PACMAN_CONF,
    STATE_ABSENT,
    STATE_PRESENT,
    build_plan,
)
from utils.packages.schema import PackageSpec


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


if __name__ == "__main__":
    unittest.main()
