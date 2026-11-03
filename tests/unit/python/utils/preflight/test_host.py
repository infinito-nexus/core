import unittest

from utils.preflight.host import disk_usage_errors

HEADER = "Filesystem     1024-blocks      Used Available Capacity Mounted on"


def _df(*rows):
    return "\n".join([HEADER, *rows]) + "\n"


class TestDiskUsageErrors(unittest.TestCase):
    def test_filesystems_at_or_below_the_limit_pass(self):
        output = _df(
            "/dev/sda1  100  90  10  90% /",
            "/dev/sdb1  100  12  88  12% /var/lib/docker",
        )
        self.assertEqual(
            disk_usage_errors(["/", "/var/lib/docker"], output, 90),
            [],
        )

    def test_a_filesystem_above_the_limit_names_path_mount_and_usage(self):
        output = _df(
            "/dev/sda1  100  50  50  50% /",
            "/dev/sda1  100  91   9  91% /srv/docker data",
        )
        self.assertEqual(
            disk_usage_errors(["/", "/srv/docker data/root"], output, 90),
            [
                "/srv/docker data/root lies on /srv/docker data, which is 91 % full (limit 90 %)"
            ],
        )

    def test_every_full_path_is_reported(self):
        output = _df(
            "overlay  100  95  5  95% /",
            "overlay  100  95  5  95% /",
        )
        self.assertEqual(
            len(disk_usage_errors(["/", "/var/lib/docker"], output, 90)), 2
        )

    def test_a_row_count_mismatch_is_rejected(self):
        with self.assertRaises(ValueError):
            disk_usage_errors(
                ["/", "/var/lib/docker"], _df("/dev/sda1 1 1 0 99% /"), 90
            )

    def test_a_row_without_a_percentage_is_rejected(self):
        with self.assertRaises(ValueError):
            disk_usage_errors(["/"], _df("/dev/sda1 1 1 0 - /"), 90)


if __name__ == "__main__":
    unittest.main()
