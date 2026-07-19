import unittest

from plugins.filter.seaweedfs import seaweedfs_command, seaweedfs_sidecar_script

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


class TestSeaweedfsSidecarScriptFilter(unittest.TestCase):
    def test_embeds_server_command(self):
        script = seaweedfs_sidecar_script("opentalk", 8333, "AK", "SK")
        self.assertIn("/entrypoint.sh " + " ".join(BASE), script)

    def test_creates_bucket_after_status_probe(self):
        script = seaweedfs_sidecar_script("opentalk", 8333, "AK", "SK")
        probe = script.index("http://127.0.0.1:8333/status")
        create = script.index("s3.bucket.create -name opentalk")
        self.assertLess(probe, create)

    def test_grants_consumer_identity_after_bucket_create(self):
        script = seaweedfs_sidecar_script("opentalk", 8333, "AKID", "SEC")
        create = script.index("s3.bucket.create -name opentalk")
        grant = script.index("s3.configure")
        self.assertLess(create, grant)
        self.assertIn("-access_key AKID", script)
        self.assertIn("-secret_key SEC", script)
        self.assertIn("-actions Read,Write,List,Tagging", script)

    def test_keeps_server_in_foreground(self):
        script = seaweedfs_sidecar_script("app", 8333, "AK", "SK")
        self.assertIn("& exec /entrypoint.sh", script)
        self.assertTrue(script.startswith("("))

    def test_contains_no_shell_dollar(self):
        self.assertNotIn("$", seaweedfs_sidecar_script("app", 8333, "AK", "SK"))


if __name__ == "__main__":
    unittest.main()
