import unittest

from plugins.filter.seaweedfs import seaweedfs_command

BASE = [
    "server",
    "-dir=/data",
    "-ip=localhost",
    "-ip.bind=0.0.0.0",
    "-filer",
    "-s3",
]


class TestSeaweedfsCommandFilter(unittest.TestCase):
    def test_sidecar_omits_s3_config(self):
        self.assertEqual(seaweedfs_command(""), BASE)

    def test_default_omits_s3_config(self):
        self.assertEqual(seaweedfs_command(), BASE)

    def test_standalone_appends_s3_config(self):
        self.assertEqual(
            seaweedfs_command("/etc/seaweedfs/s3.json"),
            [*BASE, "-s3.config=/etc/seaweedfs/s3.json"],
        )

    def test_ip_localhost_present(self):
        self.assertIn("-ip=localhost", seaweedfs_command())


if __name__ == "__main__":
    unittest.main()
