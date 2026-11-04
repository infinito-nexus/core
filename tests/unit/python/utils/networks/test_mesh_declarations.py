import unittest

from utils.networks.mesh import declared_hub, is_roaming, joined_meshes

DECLARATION = {"name": "wg0", "subnet": "10.0.0.0/24", "listen_port": 51871}


def _own(**networks) -> dict:
    return {"svc-net-wireguard": {"networks": networks}}


class TestDeclaredHub(unittest.TestCase):
    def test_a_named_hub_is_returned(self):
        self.assertEqual("galaxy", declared_hub(_own(hub="galaxy")))

    def test_an_absent_hub_is_empty(self):
        self.assertEqual("", declared_hub(_own(meshes=[DECLARATION])))

    def test_the_shipped_empty_hub_is_empty(self):
        self.assertEqual("", declared_hub(_own(hub="")))

    def test_a_hub_that_is_no_hostname_is_refused(self):
        with self.assertRaises(TypeError):
            declared_hub(_own(hub=True))


class TestRoaming(unittest.TestCase):
    def test_a_marked_host_roams(self):
        self.assertTrue(is_roaming(_own(roaming=True)))

    def test_an_unmarked_host_stays_put(self):
        self.assertFalse(is_roaming(_own()))

    def test_a_roaming_flag_that_is_no_boolean_is_refused(self):
        with self.assertRaises(TypeError):
            is_roaming(_own(roaming="yes"))


class TestJoinedMeshes(unittest.TestCase):
    def test_a_name_in_the_own_list_joins_the_host(self):
        self.assertEqual(
            {"wg0": ["svc-net-wireguard"]},
            joined_meshes(_own(meshes=["wg0"]), ["svc-net-wireguard"]),
        )

    def test_a_declaration_in_the_own_list_joins_nothing(self):
        self.assertEqual(
            {}, joined_meshes(_own(meshes=[DECLARATION]), ["svc-net-wireguard"])
        )

    def test_the_own_list_counts_only_in_the_wireguard_group(self):
        self.assertEqual({}, joined_meshes(_own(meshes=["wg0"]), ["web-app-a"]))

    def test_another_role_still_joins_its_hosts(self):
        applications = {"web-app-a": {"networks": {"meshes": ["wg0"]}}}
        self.assertEqual(
            {"wg0": ["web-app-a"]}, joined_meshes(applications, ["web-app-a"])
        )
