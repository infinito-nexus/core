import importlib.util
import unittest

from ansible.errors import AnsibleFilterError

from utils.cache.yaml import load_yaml_str

from . import PROJECT_ROOT

PLUGIN = PROJECT_ROOT / "roles" / "svc-virt-showroom" / "filter_plugins" / "showroom.py"


def _load():
    spec = importlib.util.spec_from_file_location("showroom", PLUGIN)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


showroom = _load()

KARAKALPAK = {
    "flavor": "vm",
    "image": "images:debian/12/cloud",
    "cpus": 4,
    "memory": "12GiB",
    "disk": "80GiB",
    "address": "192.168.245.10",
    "domains": [
        "karakalpakstan.demo.infinito.nexus",
        "auth.karakalpakstan.demo.infinito.nexus",
    ],
    "ssh_authorized_keys": ["ssh-ed25519 AAAAkey operator@workstation"],
}

LAB = {
    "flavor": "container",
    "image": "images:debian/12/cloud",
    "cpus": 2,
    "memory": "6GiB",
    "disk": "20GiB",
    "address": "192.168.245.11",
    "domains": ["lab.demo.infinito.nexus"],
    "ssh_authorized_keys": [],
}


class TestBudget(unittest.TestCase):
    def test_a_list_within_the_budget_passes(self):
        self.assertEqual(
            [], showroom.budget_errors({"karakalpak": KARAKALPAK}, "16GiB")
        )

    def test_a_list_over_the_budget_names_every_project_and_its_memory(self):
        errors = showroom.budget_errors({"karakalpak": KARAKALPAK, "lab": LAB}, "16GiB")
        self.assertEqual(1, len(errors))
        self.assertIn("karakalpak: 12GiB", errors[0])
        self.assertIn("lab: 6GiB", errors[0])
        self.assertIn("16GiB", errors[0])

    def test_the_budget_is_inclusive(self):
        self.assertEqual(
            [],
            showroom.budget_errors(
                {"karakalpak": KARAKALPAK, "lab": {**LAB, "memory": "4GiB"}},
                "16GiB",
            ),
        )

    def test_no_projects_fit_any_budget(self):
        self.assertEqual([], showroom.budget_errors({}, "16GiB"))


class TestKvm(unittest.TestCase):
    def test_a_vm_project_without_kvm_is_refused_with_the_way_out(self):
        errors = showroom.kvm_errors({"karakalpak": KARAKALPAK, "lab": LAB}, False)
        self.assertEqual(1, len(errors))
        self.assertIn("'karakalpak'", errors[0])
        self.assertIn("flavor: container", errors[0])

    def test_a_vm_project_with_kvm_passes(self):
        self.assertEqual([], showroom.kvm_errors({"karakalpak": KARAKALPAK}, True))

    def test_a_project_without_flavor_is_a_vm(self):
        entry = {key: value for key, value in KARAKALPAK.items() if key != "flavor"}
        self.assertEqual(1, len(showroom.kvm_errors({"karakalpak": entry}, False)))

    def test_an_unknown_flavor_is_refused(self):
        with self.assertRaises(AnsibleFilterError):
            showroom.kvm_errors({"karakalpak": {**KARAKALPAK, "flavor": "lxc"}}, True)


class AnsibleLazyDictStandIn(dict):
    pass


class TestInstances(unittest.TestCase):
    def setUp(self):
        self.instances = {
            item["name"]: item
            for item in showroom.instances(
                {"karakalpak": KARAKALPAK, "lab": LAB}, "showroom", "showroombr0"
            )
        }

    def test_the_vm_carries_the_entry_limits_and_no_nesting(self):
        vm = self.instances["karakalpak"]
        self.assertTrue(vm["vm"])
        self.assertEqual("karakalpak", vm["project"])
        self.assertEqual({"limits.cpu": "4", "limits.memory": "12GiB"}, vm["config"])

    def test_the_container_allows_nesting(self):
        container = self.instances["lab"]
        self.assertFalse(container["vm"])
        self.assertEqual("true", container["config"]["security.nesting"])

    def test_the_root_disk_and_the_fixed_address(self):
        devices = self.instances["karakalpak"]["devices"]
        self.assertEqual(
            {"type": "disk", "path": "/", "pool": "showroom", "size": "80GiB"},
            devices["root"],
        )
        self.assertEqual(
            {
                "type": "nic",
                "network": "showroombr0",
                "ipv4.address": "192.168.245.10",
            },
            devices["eth0"],
        )

    def test_the_creation_document_installs_the_keys_for_root(self):
        document = load_yaml_str(showroom.creation_yaml(self.instances["karakalpak"]))
        user_data = document["config"]["cloud-init.user-data"]
        self.assertTrue(user_data.startswith("#cloud-config\n"))
        cloud = load_yaml_str(user_data)
        self.assertEqual(
            [
                {
                    "name": "root",
                    "ssh_authorized_keys": KARAKALPAK["ssh_authorized_keys"],
                }
            ],
            cloud["users"],
        )
        self.assertFalse(cloud["disable_root"])
        self.assertEqual(["openssh-server", "systemd-timesyncd"], cloud["packages"])
        self.assertEqual("12GiB", document["config"]["limits.memory"])
        self.assertEqual("80GiB", document["devices"]["root"]["size"])

    def test_the_creation_document_accepts_ansible_dict_subclasses(self):
        vm = self.instances["karakalpak"]
        looped = AnsibleLazyDictStandIn(
            vm,
            devices=AnsibleLazyDictStandIn(
                {name: AnsibleLazyDictStandIn(d) for name, d in vm["devices"].items()}
            ),
        )
        document = load_yaml_str(showroom.creation_yaml(looped))
        self.assertEqual(vm["devices"], document["devices"])

    def test_password_logins_go_off_through_a_drop_in_not_the_main_config(self):
        cloud = load_yaml_str(
            load_yaml_str(showroom.creation_yaml(self.instances["karakalpak"]))[
                "config"
            ]["cloud-init.user-data"]
        )
        self.assertNotIn("ssh_pwauth", cloud)
        self.assertEqual(
            [
                {
                    "path": "/etc/ssh/sshd_config.d/60-showroom.conf",
                    "permissions": "0644",
                    "content": "PasswordAuthentication no\n",
                }
            ],
            cloud["write_files"],
        )

    def test_settings_cover_limits_size_and_address(self):
        rows = {
            (row["device"], row["key"]): row["value"]
            for row in showroom.settings([self.instances["karakalpak"]])
        }
        self.assertEqual(
            {
                ("", "limits.cpu"): "4",
                ("", "limits.memory"): "12GiB",
                ("root", "size"): "80GiB",
                ("eth0", "ipv4.address"): "192.168.245.10",
            },
            rows,
        )


class TestVhosts(unittest.TestCase):
    def test_every_domain_points_at_port_443_of_its_project(self):
        self.assertEqual(
            [
                {
                    "domain": "karakalpakstan.demo.infinito.nexus",
                    "project": "karakalpak",
                    "upstream": "192.168.245.10:443",
                },
                {
                    "domain": "auth.karakalpakstan.demo.infinito.nexus",
                    "project": "karakalpak",
                    "upstream": "192.168.245.10:443",
                },
                {
                    "domain": "lab.demo.infinito.nexus",
                    "project": "lab",
                    "upstream": "192.168.245.11:443",
                },
            ],
            showroom.vhosts({"karakalpak": KARAKALPAK, "lab": LAB}),
        )

    def test_a_domain_of_two_projects_is_refused(self):
        with self.assertRaises(AnsibleFilterError):
            showroom.vhosts(
                {
                    "karakalpak": KARAKALPAK,
                    "lab": {**LAB, "domains": KARAKALPAK["domains"]},
                }
            )

    def test_domains_are_flattened_and_sorted(self):
        self.assertEqual(
            sorted(KARAKALPAK["domains"] + LAB["domains"]),
            showroom.domains({"karakalpak": KARAKALPAK, "lab": LAB}),
        )


class TestRegistry(unittest.TestCase):
    def test_every_filter_is_registered(self):
        self.assertEqual(
            {
                "showroom_budget_errors",
                "showroom_kvm_errors",
                "showroom_instances",
                "showroom_creation_yaml",
                "showroom_settings",
                "showroom_domains",
                "showroom_vhosts",
            },
            set(showroom.FilterModule().filters()),
        )


if __name__ == "__main__":
    unittest.main()
