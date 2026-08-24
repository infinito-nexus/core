import unittest

from plugins.filter.seaweedfs import (
    MIN_FREE_SPACE_VOLUMES,
    VOLUME_GROW_BATCH,
    VOLUME_SIZE_LIMIT_MB,
    min_free_space,
    seaweedfs_command,
    seaweedfs_sidecar_script,
    volume_slots,
)

BASE = [
    "server",
    "-dir=/data",
    "-ip=localhost",
    "-ip.bind=0.0.0.0",
    f"-master.volumeSizeLimitMB={VOLUME_SIZE_LIMIT_MB}",
    f"-volume.max={volume_slots(1)}",
    f"-volume.minFreeSpace={min_free_space()}",
    "-filer",
    "-s3",
]


class TestSeaweedfsCommandFilter(unittest.TestCase):
    def test_sidecar_omits_s3_config(self):
        self.assertEqual(seaweedfs_command("", collections=1), BASE)

    def test_standalone_appends_s3_config(self):
        self.assertEqual(
            seaweedfs_command("/etc/seaweedfs/s3.json", collections=1),
            [*BASE, "-s3.config=/etc/seaweedfs/s3.json"],
        )

    def test_ip_localhost_present(self):
        self.assertIn("-ip=localhost", seaweedfs_command(collections=1))

    def test_volume_slots_are_stated_so_the_entrypoint_does_not_autosize(self):
        command = seaweedfs_command(collections=1)
        self.assertIn(f"-volume.max={volume_slots(1)}", command)
        self.assertNotIn("-volume.max=0", command)

    def test_a_missing_collection_count_is_refused(self):
        with self.assertRaises(ValueError):
            seaweedfs_command("/etc/seaweedfs/s3.json")

    def test_slots_cover_every_consumer_plus_the_default_collection(self):
        self.assertEqual(volume_slots(0), VOLUME_GROW_BATCH)
        self.assertEqual(volume_slots(54), 55 * VOLUME_GROW_BATCH)

    def test_slots_accept_the_string_a_jinja_lookup_yields(self):
        self.assertEqual(volume_slots("54"), volume_slots(54))

    def test_the_free_space_floor_clears_a_whole_allocation_unit(self):
        floor_mb = int(min_free_space().removesuffix("MiB"))
        self.assertGreaterEqual(floor_mb, VOLUME_SIZE_LIMIT_MB)
        self.assertEqual(floor_mb, VOLUME_SIZE_LIMIT_MB * MIN_FREE_SPACE_VOLUMES)

    def test_the_volume_size_limit_is_stated_not_inherited(self):
        command = seaweedfs_command(collections=1)
        self.assertIn(f"-master.volumeSizeLimitMB={VOLUME_SIZE_LIMIT_MB}", command)
        self.assertIn(f"-volume.minFreeSpace={min_free_space()}", command)


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
