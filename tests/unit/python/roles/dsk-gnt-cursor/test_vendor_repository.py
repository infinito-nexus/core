from __future__ import annotations

import unittest

from utils.cache.files import PROJECT_ROOT
from utils.packages.calls import STATE_PRESENT
from utils.packages.plan import build_plan
from utils.packages.registry import build_registry, resolve

PACKAGE_ID = "cursor"
APT_SOURCES = [
    "/etc/apt/sources.list.d/cursor.list",
    "/etc/apt/sources.list.d/cursor.sources",
]
YUM_REPO = ["/etc/yum.repos.d/cursor.repo"]
VENDOR_REPO_FILES: dict[str, list[str]] = {
    "centos": YUM_REPO,
    "debian": APT_SOURCES,
    "fedora": YUM_REPO,
    "ubuntu": APT_SOURCES,
}
LOCAL_INSTALL_MODULES = frozenset({"ansible.builtin.apt", "ansible.builtin.dnf"})


def _removed_after_install(distro: str) -> list[str]:
    spec = resolve(build_registry(PROJECT_ROOT)[PACKAGE_ID], distro)
    plan = build_plan(spec, STATE_PRESENT)
    install = next(
        index for index, call in enumerate(plan) if call.module in LOCAL_INSTALL_MODULES
    )
    return [
        call.args["path"]
        for call in plan[install + 1 : -1]
        if call.module == "ansible.builtin.file" and call.args.get("state") == "absent"
    ]


class TestCursorVendorRepository(unittest.TestCase):
    def test_the_repository_the_artefact_registers_is_removed(self) -> None:
        for distro, repo_files in VENDOR_REPO_FILES.items():
            with self.subTest(distro=distro):
                self.assertEqual(
                    _removed_after_install(distro),
                    repo_files,
                    "the pinned cursor rpm's %post writes /etc/yum.repos.d/"
                    "cursor.repo (repo_gpgcheck=1) and the deb's postinst "
                    "writes cursor.list or cursor.sources under "
                    "/etc/apt/sources.list.d; left in place, every "
                    "roles/update run depends on the vendor repository and "
                    "its full upgrade moves cursor past the pinned artefact",
                )


if __name__ == "__main__":
    unittest.main()
