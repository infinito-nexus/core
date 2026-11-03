import unittest

from ansible.errors import AnsibleFilterError

from plugins.filter.preflight import (
    FilterModule,
    preflight_disk_usage,
    preflight_port_cgroups,
    preflight_port_conflicts,
)

SS_LINES = (
    'tcp LISTEN 0 100 0.0.0.0:25 0.0.0.0:* users:(("master",pid=812,fd=13))',
    'tcp LISTEN 0 511 0.0.0.0:80 0.0.0.0:* users:(("nginx",pid=3001,fd=6))',
    'tcp LISTEN 0 511 0.0.0.0:443 0.0.0.0:* users:(("docker-proxy",pid=7,fd=4))',
)
SS = "\n".join(SS_LINES)
PORTS = {
    "25": ["web-app-mailu (mailu.smtp)"],
    "80": ["svc-prx-openresty (openresty.http)"],
    "443": ["svc-prx-openresty (openresty.https)"],
}


class TestPreflightFilters(unittest.TestCase):
    def test_the_filters_are_registered(self):
        self.assertEqual(
            set(FilterModule().filters()),
            {
                "preflight_disk_usage",
                "preflight_port_cgroups",
                "preflight_port_conflicts",
            },
        )

    def test_disk_usage_reads_df_against_the_limit(self):
        output = "Filesystem 1024-blocks Used Available Capacity Mounted on\n/dev/sda1 10 9 1 95% /\n"
        self.assertEqual(
            preflight_disk_usage(output, ["/"], "90"),
            ["/ lies on /, which is 95 % full (limit 90 %)"],
        )

    def test_unparsable_df_output_is_a_filter_error(self):
        with self.assertRaises(AnsibleFilterError):
            preflight_disk_usage("header only\n", ["/"], 90)

    def test_the_cgroup_files_of_non_docker_listeners_are_listed(self):
        self.assertEqual(
            preflight_port_cgroups(SS, PORTS),
            ["/proc/812/cgroup", "/proc/3001/cgroup"],
        )

    def test_unparsable_ss_output_is_a_filter_error(self):
        with self.assertRaises(AnsibleFilterError):
            preflight_port_cgroups("garbage", PORTS)
        with self.assertRaises(AnsibleFilterError):
            preflight_port_conflicts("garbage", {"skipped": True}, PORTS)

    def test_a_containerised_listener_passes_and_a_host_one_fails(self):
        probe = {
            "stdout": "/proc/812/cgroup:0::/system.slice/postfix.service\n"
            "/proc/3001/cgroup:0::/system.slice/docker-0123456789abcdef.scope"
        }
        self.assertEqual(
            preflight_port_conflicts(SS, probe, PORTS),
            [
                (
                    "master (pid 812) listens on tcp 0.0.0.0:25, "
                    "which web-app-mailu (mailu.smtp) binds"
                )
            ],
        )

    def test_a_skipped_cgroup_probe_means_no_container(self):
        ss = 'tcp LISTEN 0 1 0.0.0.0:443 0.0.0.0:* users:(("docker-proxy",pid=7,fd=4))'
        self.assertEqual(preflight_port_conflicts(ss, {"skipped": True}, PORTS), [])


if __name__ == "__main__":
    unittest.main()
