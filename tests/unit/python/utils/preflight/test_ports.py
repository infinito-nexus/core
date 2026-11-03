import unittest

from utils.preflight.ports import (
    Listener,
    containerised_pids,
    parse_listeners,
    port_conflicts,
    probed_pids,
    suspect_pids,
)

SS_LINES = (
    'tcp   LISTEN 0 100  0.0.0.0:25      0.0.0.0:*  users:(("master",pid=812,fd=13))',
    'tcp   LISTEN 0 4096 [::]:443        [::]:*     users:(("docker-proxy",pid=2001,fd=4))',
    'tcp   LISTEN 0 511  0.0.0.0:80      0.0.0.0:*  users:(("nginx",pid=3001,fd=6),("nginx",pid=3002,fd=6))',
    'udp   UNCONN 0 0    127.0.0.53%lo:53 0.0.0.0:* users:(("systemd-resolve",pid=501,fd=13))',
    "udp   UNCONN 0 0    0.0.0.0:3478    0.0.0.0:*",
    'tcp   LISTEN 0 128  0.0.0.0:22      0.0.0.0:*  users:(("sshd",pid=700,fd=3))',
)
SS = "\n".join(SS_LINES)
PORTS = {
    25: ["web-app-mailu (mailu.smtp)"],
    80: ["svc-prx-openresty (openresty.http)"],
    443: ["svc-prx-openresty (openresty.https)"],
    3478: ["web-svc-coturn (coturn.stun_turn)"],
}
CGROUP_LINES = (
    "/proc/812/cgroup:0::/system.slice/postfix.service",
    "/proc/3001/cgroup:0::/system.slice/docker-0123456789abcdef0123.scope",
    "/proc/3002/cgroup:0::/docker/0123456789abcdef0123456789abcdef",
)
CGROUPS = "\n".join(CGROUP_LINES)
PROBED = {812, 3001, 3002}


class TestParseListeners(unittest.TestCase):
    def test_lines_yield_protocol_address_port_and_processes(self):
        listeners = parse_listeners(SS)
        self.assertEqual(
            listeners[1],
            Listener("tcp", "[::]", 443, (("docker-proxy", 2001),)),
        )
        self.assertEqual(listeners[2].processes, (("nginx", 3001), ("nginx", 3002)))
        self.assertEqual(listeners[3].address, "127.0.0.53%lo")
        self.assertEqual(listeners[4].processes, ())

    def test_an_ipv6_address_keeps_its_brackets(self):
        self.assertEqual(parse_listeners(SS)[1].address, "[::]")

    def test_an_unparsable_line_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_listeners("tcp LISTEN 0 1 nonsense")


class TestSuspectPids(unittest.TestCase):
    def test_only_non_docker_processes_on_deploy_ports_are_suspects(self):
        self.assertEqual(suspect_pids(parse_listeners(SS), PORTS), [812, 3001, 3002])


class TestContainerisedPids(unittest.TestCase):
    def test_docker_and_podman_cgroups_count_as_containers(self):
        output = (
            CGROUPS + "\n/proc/9/cgroup:0::/machine.slice/libpod-0123456789abcdef.scope"
        )
        self.assertEqual(containerised_pids(output), {3001, 3002, 9})

    def test_the_docker_daemon_unit_is_no_container(self):
        self.assertEqual(
            containerised_pids("/proc/40/cgroup:0::/system.slice/docker.service"), set()
        )


class TestPortConflicts(unittest.TestCase):
    def test_host_processes_and_ownerless_sockets_conflict(self):
        self.assertEqual(
            port_conflicts(
                parse_listeners(SS), containerised_pids(CGROUPS), PORTS, PROBED
            ),
            [
                "master (pid 812) listens on tcp 0.0.0.0:25, which web-app-mailu (mailu.smtp) binds",
                (
                    "a socket without a process listens on udp 0.0.0.0:3478, "
                    "which web-svc-coturn (coturn.stun_turn) binds"
                ),
            ],
        )

    def test_a_host_networked_container_and_docker_proxy_pass(self):
        listeners = parse_listeners(SS)[1:3]
        self.assertEqual(
            port_conflicts(listeners, containerised_pids(CGROUPS), PORTS, PROBED), []
        )

    def test_a_process_whose_cgroup_is_unknown_conflicts(self):
        listeners = parse_listeners(SS)[2:3]
        self.assertEqual(
            port_conflicts(listeners, {3001}, PORTS, PROBED),
            [
                (
                    "nginx (pid 3002) listens on tcp 0.0.0.0:80, "
                    "which svc-prx-openresty (openresty.http) binds"
                )
            ],
        )

    def test_a_process_that_exited_before_its_cgroup_was_read_passes(self):
        listeners = parse_listeners(SS)[2:3]
        self.assertEqual(port_conflicts(listeners, {3001}, PORTS, {3001}), [])

    def test_probed_pids_lists_every_pid_with_a_cgroup_line(self):
        self.assertEqual(probed_pids(CGROUPS), PROBED)

    def test_ports_the_deploy_does_not_bind_pass(self):
        listeners = [parse_listeners(SS)[5]]
        self.assertEqual(port_conflicts(listeners, set(), PORTS, PROBED), [])


if __name__ == "__main__":
    unittest.main()
