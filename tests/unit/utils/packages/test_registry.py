import tempfile
import unittest
from pathlib import Path

from utils.cache.yaml import dump_yaml
from utils.packages.registry import (
    build_registry,
    iter_inventory_package_lists,
    load_declarations,
    resolve,
)
from utils.packages.schema import (
    DISTRO_FAMILY,
    SOURCE_AUR,
    SOURCE_REPO,
    PackagesShapeError,
)


def _write_role(root: Path, role: str, payload) -> None:
    meta = root / "roles" / role / "meta"
    meta.mkdir(parents=True, exist_ok=True)
    dump_yaml(str(meta / "packages.yml"), payload)


def _write_shared(root: Path, payload) -> None:
    meta = root / "meta"
    meta.mkdir(parents=True, exist_ok=True)
    dump_yaml(str(meta / "packages.yml"), payload)


def _write_inventory(root: Path, name: str, payload) -> None:
    directory = root / "inventories" / name
    directory.mkdir(parents=True, exist_ok=True)
    dump_yaml(str(directory / "inventory.yml"), payload)


class TestRegistry(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _declaration(self, package_id: str):
        return build_registry(self.root)[package_id]

    def test_bare_list_is_repo_source(self):
        _write_role(self.root, "role-a", {"git": {"Debian": ["git"]}})
        spec = resolve(self._declaration("git"), "debian")
        self.assertEqual(spec.names, ("git",))
        self.assertEqual(spec.source, SOURCE_REPO)
        self.assertIsNone(spec.repo)

    def test_distro_override_beats_family(self):
        _write_role(
            self.root,
            "role-a",
            {
                "nfs-ganesha": {
                    "RedHat": ["nfs-ganesha"],
                    "centos": {
                        "names": ["nfs-ganesha"],
                        "repo": {"baseurl": "https://sig.example/repo/"},
                    },
                }
            },
        )
        declaration = self._declaration("nfs-ganesha")
        self.assertIsNone(resolve(declaration, "fedora").repo)
        self.assertEqual(
            resolve(declaration, "centos").repo["baseurl"], "https://sig.example/repo/"
        )

    def test_ubuntu_resolves_through_debian_family(self):
        _write_role(self.root, "role-a", {"git": {"Debian": ["git"]}})
        self.assertEqual(resolve(self._declaration("git"), "ubuntu").names, ("git",))

    def test_aur_source(self):
        _write_role(
            self.root,
            "role-a",
            {"nfs-ganesha": {"Archlinux": {"source": "aur", "names": ["nfs-ganesha"]}}},
        )
        spec = resolve(self._declaration("nfs-ganesha"), "arch")
        self.assertEqual(spec.source, SOURCE_AUR)

    def test_empty_list_is_covered_but_installs_nothing(self):
        _write_role(self.root, "role-a", {"python-selinux": {"Debian": []}})
        spec = resolve(self._declaration("python-selinux"), "debian")
        self.assertIsNotNone(spec)
        self.assertEqual(spec.names, ())

    def test_virtual_flag_is_carried(self):
        _write_role(
            self.root,
            "role-a",
            {"nodejs": {"RedHat": {"names": ["nodejs"], "virtual": True}}},
        )
        self.assertTrue(resolve(self._declaration("nodejs"), "fedora").virtual)

    def test_virtual_defaults_to_false(self):
        _write_role(self.root, "role-a", {"git": {"Debian": ["git"]}})
        self.assertFalse(resolve(self._declaration("git"), "debian").virtual)

    def test_non_boolean_virtual_raises(self):
        _write_role(
            self.root,
            "role-a",
            {"git": {"Debian": {"names": ["git"], "virtual": "yes"}}},
        )
        with self.assertRaises(PackagesShapeError):
            resolve(self._declaration("git"), "debian")

    def test_inline_repo_is_carried(self):
        _write_role(
            self.root,
            "role-a",
            {
                "micro": {
                    "centos": {
                        "names": ["micro"],
                        "repo": {"bootstrap_package": "epel-release"},
                    }
                }
            },
        )
        spec = resolve(self._declaration("micro"), "centos")
        self.assertEqual(spec.repo["bootstrap_package"], "epel-release")

    def test_repo_as_string_raises(self):
        _write_role(
            self.root,
            "role-a",
            {"micro": {"centos": {"names": ["micro"], "repo": "epel"}}},
        )
        with self.assertRaises(PackagesShapeError):
            resolve(self._declaration("micro"), "centos")

    def test_repo_without_a_known_key_raises(self):
        _write_role(
            self.root,
            "role-a",
            {"micro": {"centos": {"names": ["micro"], "repo": {"name": "x"}}}},
        )
        with self.assertRaises(PackagesShapeError):
            resolve(self._declaration("micro"), "centos")

    def test_missing_key_is_a_gap(self):
        _write_role(self.root, "role-a", {"git": {"Debian": ["git"]}})
        self.assertIsNone(resolve(self._declaration("git"), "arch"))

    def test_duplicate_id_across_roles_raises(self):
        _write_role(self.root, "role-a", {"git": {"Debian": ["git"]}})
        _write_role(self.root, "role-b", {"git": {"Debian": ["git"]}})
        with self.assertRaises(PackagesShapeError) as ctx:
            build_registry(self.root)
        self.assertIn("declared twice", str(ctx.exception))

    def test_unknown_source_raises(self):
        _write_role(
            self.root,
            "role-a",
            {"git": {"Debian": {"names": ["git"], "source": "snap"}}},
        )
        with self.assertRaises(PackagesShapeError):
            resolve(self._declaration("git"), "debian")

    def test_unknown_distro_raises_without_family(self):
        _write_role(self.root, "role-a", {"git": {"Debian": ["git"]}})
        with self.assertRaises(PackagesShapeError):
            resolve(self._declaration("git"), "gentoo")

    def test_distro_outside_the_matrix_resolves_through_given_family(self):
        _write_role(self.root, "role-a", {"sudo": {"Archlinux": ["sudo"]}})
        spec = resolve(self._declaration("sudo"), "manjarolinux", "Archlinux")
        self.assertEqual(spec.names, ("sudo",))

    def test_given_family_still_loses_to_a_distro_override(self):
        _write_role(
            self.root,
            "role-a",
            {"pkg": {"RedHat": ["base"], "centos": ["override"]}},
        )
        spec = resolve(self._declaration("pkg"), "centos", "RedHat")
        self.assertEqual(spec.names, ("override",))

    def test_declarations_carry_role_provenance(self):
        _write_role(self.root, "role-a", {"git": {"Debian": ["git"]}})
        declarations = load_declarations(self.root)
        self.assertEqual(declarations[0].role, "role-a")
        self.assertFalse(declarations[0].shared)
        self.assertEqual(declarations[0].owner, "role-a")

    def test_root_declarations_are_shared(self):
        _write_shared(self.root, {"git": {"Debian": ["git"]}})
        declaration = self._declaration("git")
        self.assertIsNone(declaration.role)
        self.assertTrue(declaration.shared)
        self.assertEqual(resolve(declaration, "debian").names, ("git",))

    def test_id_declared_both_shared_and_by_a_role_raises(self):
        _write_shared(self.root, {"git": {"Debian": ["git"]}})
        _write_role(self.root, "role-a", {"git": {"Debian": ["git"]}})
        with self.assertRaises(PackagesShapeError) as ctx:
            build_registry(self.root)
        self.assertIn("declared twice", str(ctx.exception))

    def test_inventory_package_lists_are_collected(self):
        _write_inventory(
            self.root, "bundle", {"all": {"vars": {"PACKAGES": ["git", "cmake"]}}}
        )
        collected = list(iter_inventory_package_lists(self.root))
        self.assertEqual([ids for _path, ids in collected], [["git", "cmake"]])

    def test_inventory_without_packages_is_skipped(self):
        _write_inventory(self.root, "bundle", {"all": {"vars": {"OTHER": 1}}})
        self.assertEqual(list(iter_inventory_package_lists(self.root)), [])

    def test_inventory_packages_as_mapping_raises(self):
        _write_inventory(
            self.root, "bundle", {"all": {"vars": {"PACKAGES": {"repo": ["git"]}}}}
        )
        with self.assertRaises(PackagesShapeError):
            list(iter_inventory_package_lists(self.root))

    def test_default_matrix_covers_five_distros(self):
        self.assertEqual(
            sorted(DISTRO_FAMILY), ["arch", "centos", "debian", "fedora", "ubuntu"]
        )


if __name__ == "__main__":
    unittest.main()
