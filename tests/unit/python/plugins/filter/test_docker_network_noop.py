import unittest

from ansible.errors import AnsibleFilterError

from plugins.filter.docker.network_noop import docker_network_noop


class TestDockerNetworkNoop(unittest.TestCase):
    def test_connect_already_attached_is_noop(self):
        self.assertTrue(
            docker_network_noop(
                "Error response from daemon: endpoint with name discourse "
                "already exists in network postgres",
                "connect",
            )
        )
        self.assertTrue(
            docker_network_noop(
                "container already attached to network discourse", "connect"
            )
        )

    def test_disconnect_absence_variants_are_noop(self):
        for stderr in (
            "Error response from daemon: container abc is not connected to network discourse",
            "Error response from daemon: network discourse not found",
            "Error response from daemon: No such container: postgres",
            "Error: No such network: discourse",
        ):
            self.assertTrue(docker_network_noop(stderr, "disconnect"))

    def test_case_insensitive(self):
        self.assertTrue(
            docker_network_noop("ERROR: NO SUCH CONTAINER: postgres", "disconnect")
        )

    def test_real_errors_stay_false(self):
        for stderr in (
            "Error response from daemon: network discourse has active endpoints",
            "permission denied while trying to connect to the Docker daemon socket",
            "Cannot connect to the Docker daemon at unix:///var/run/docker.sock",
            "",
            None,
        ):
            self.assertFalse(docker_network_noop(stderr, "disconnect"))
            self.assertFalse(docker_network_noop(stderr, "connect"))

    def test_connect_markers_not_valid_for_disconnect(self):
        self.assertFalse(
            docker_network_noop("already exists in network foo", "disconnect")
        )
        self.assertFalse(
            docker_network_noop("is not connected to network foo", "connect")
        )

    def test_unknown_operation_raises(self):
        with self.assertRaises(AnsibleFilterError):
            docker_network_noop("anything", "attach")


if __name__ == "__main__":
    unittest.main()
