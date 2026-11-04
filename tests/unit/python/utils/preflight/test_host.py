import unittest

from utils.preflight.host import disk_usage_errors

HEADER = "Filesystem     1024-blocks      Used Available Capacity Mounted on"
FLOOR_GB = 20
KIB_AT_FLOOR = FLOOR_GB * 10**9 // 1024


def _df(*rows):
    return "\n".join([HEADER, *rows]) + "\n"


class TestDiskUsageErrors(unittest.TestCase):
    def test_filesystems_at_or_below_the_percentage_pass(self):
        output = _df(
            "/dev/sda1  100  90  10  90% /",
            "/dev/sdb1  100  12  88  12% /var/lib/docker",
        )
        self.assertEqual(
            disk_usage_errors(["/", "/var/lib/docker"], output, 90, FLOOR_GB),
            [],
        )

    def test_a_full_filesystem_short_of_the_floor_names_path_mount_usage_and_room(self):
        output = _df(
            "/dev/sda1  100  50  50  50% /",
            "/dev/sda1  100  91   9  91% /srv/docker data",
        )
        self.assertEqual(
            disk_usage_errors(["/", "/srv/docker data/root"], output, 90, FLOOR_GB),
            [
                (
                    "/srv/docker data/root lies on /srv/docker data, which is 91 % full "
                    "with 0.0 GB free (limits 90 % and 20 GB)"
                )
            ],
        )

    def test_a_big_disk_above_the_percentage_with_room_left_passes(self):
        output = _df("/dev/mapper/root  1900000000  1870000000  30000000  99% /")
        self.assertEqual(disk_usage_errors(["/"], output, 90, FLOOR_GB), [])

    def test_room_exactly_at_the_floor_passes(self):
        output = _df(f"/dev/mapper/root  1900000000  1880000000  {KIB_AT_FLOOR}  99% /")
        self.assertEqual(disk_usage_errors(["/"], output, 90, FLOOR_GB), [])

    def test_room_just_below_the_floor_fails(self):
        output = _df(
            f"/dev/mapper/root  1900000000  1880000000  {KIB_AT_FLOOR - 1}  99% /"
        )
        self.assertEqual(len(disk_usage_errors(["/"], output, 90, FLOOR_GB)), 1)

    def test_a_small_disk_below_the_percentage_passes_with_little_room(self):
        output = _df("/dev/sda1  2000000  1000000  1000000  50% /")
        self.assertEqual(disk_usage_errors(["/"], output, 90, FLOOR_GB), [])

    def test_every_full_path_is_reported(self):
        output = _df(
            "overlay  100  95  5  95% /",
            "overlay  100  95  5  95% /",
        )
        self.assertEqual(
            len(disk_usage_errors(["/", "/var/lib/docker"], output, 90, FLOOR_GB)), 2
        )

    def test_a_row_count_mismatch_is_rejected(self):
        with self.assertRaises(ValueError):
            disk_usage_errors(
                ["/", "/var/lib/docker"], _df("/dev/sda1 1 1 0 99% /"), 90, FLOOR_GB
            )

    def test_a_row_without_a_percentage_is_rejected(self):
        with self.assertRaises(ValueError):
            disk_usage_errors(["/"], _df("/dev/sda1 1 1 0 - /"), 90, FLOOR_GB)

    def test_a_row_without_an_available_count_is_rejected(self):
        with self.assertRaises(ValueError):
            disk_usage_errors(["/"], _df("/dev/sda1 1 1 - 99% /"), 90, FLOOR_GB)


if __name__ == "__main__":
    unittest.main()
