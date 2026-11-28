import json
import unittest

from ansible.errors import AnsibleFilterError

from plugins.filter.seaweedfs import (
    ANONYMOUS_DENY_SID,
    MIN_FREE_SPACE_VOLUMES,
    VOLUME_GROW_BATCH,
    VOLUME_SIZE_LIMIT_MB,
    WORKSPACE_MAX_KEY,
    min_free_space,
    seaweedfs_anonymous_deny_policy,
    seaweedfs_bucket_names,
    seaweedfs_bucket_policy_target,
    seaweedfs_bucket_state_files,
    seaweedfs_command,
    seaweedfs_location_configured,
    seaweedfs_s3_identities,
    seaweedfs_sidecar_script,
    seaweedfs_stored_bucket_policy,
    seaweedfs_versioning_enabled,
    seaweedfs_workspace,
    seaweedfs_workspace_credentials,
    seaweedfs_workspace_identity,
    seaweedfs_workspace_slot,
    volume_slots,
)

WORKSPACE_A = "0b5e8c1e-6f43-4c3a-9d6b-2a1f0e9c7d11"
WORKSPACE_B = "7c2d9e40-1a5b-4e8f-b3c6-90d4a2f1e5aa"
ADMIN = {
    "name": "admin",
    "credentials": [{"accessKey": "admin-ak", "secretKey": "admin-sk"}],
    "actions": ["Admin", "Read", "Write", "List", "Tagging"],
}

FOREIGN_STATEMENT = {
    "Sid": "OperatorReadOnly",
    "Effect": "Allow",
    "Principal": {"AWS": ["arn:aws:iam::000000000000:user/auditor"]},
    "Action": "s3:GetObject",
    "Resource": "arn:aws:s3:::mastodon/*",
}

NO_SUCH_BUCKET_POLICY_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    "<Error><Code>NoSuchBucketPolicy</Code>"
    "<Message>The bucket policy does not exist</Message>"
    "<Resource>/mastodon</Resource><RequestId>1</RequestId>"
    "<BucketName>mastodon</BucketName></Error>"
)

NO_SUCH_BUCKET_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    "<Error><Code>NoSuchBucket</Code>"
    "<Message>The specified bucket does not exist</Message>"
    "<Resource>/mastodon</Resource><RequestId>1</RequestId>"
    "<BucketName>mastodon</BucketName></Error>"
)


def _deny(bucket="mastodon"):
    (statement,) = seaweedfs_anonymous_deny_policy(bucket)["Statement"]
    return statement


def _go_marshal(value):
    """Mirror how SeaweedFS 4.51 re-serialises a stored policy.

    Args:
        value: policy fragment; every one-element string list collapses to
            its string, as ``StringOrStringSlice.MarshalJSON`` does.
    """
    if isinstance(value, dict):
        return {key: _go_marshal(item) for key, item in value.items()}
    if isinstance(value, list) and len(value) == 1 and isinstance(value[0], str):
        return value[0]
    if isinstance(value, list):
        return [_go_marshal(item) for item in value]
    return value


def _curl_output(body, status):
    return f"{body}\n{status}"


BASE = [
    "server",
    "-dir=/data",
    "-ip=localhost",
    "-ip.bind=0.0.0.0",
    f"-master.volumeSizeLimitMB={VOLUME_SIZE_LIMIT_MB}",
    f"-volume.max={volume_slots(1, 0)}",
    f"-volume.minFreeSpace={min_free_space()}",
    "-filer",
    "-s3",
]


class TestSeaweedfsCommandFilter(unittest.TestCase):
    def test_sidecar_omits_s3_config(self):
        self.assertEqual(seaweedfs_command("", collections=1, workspaces=0), BASE)

    def test_standalone_appends_s3_config(self):
        self.assertEqual(
            seaweedfs_command("/etc/seaweedfs/s3/s3.json", collections=1, workspaces=0),
            [*BASE, "-s3.config=/etc/seaweedfs/s3/s3.json"],
        )

    def test_ip_localhost_present(self):
        self.assertIn("-ip=localhost", seaweedfs_command(collections=1, workspaces=0))

    def test_volume_slots_are_stated_so_the_entrypoint_does_not_autosize(self):
        command = seaweedfs_command(collections=1, workspaces=0)
        self.assertIn(f"-volume.max={volume_slots(1, 0)}", command)
        self.assertNotIn("-volume.max=0", command)

    def test_a_missing_collection_count_is_refused(self):
        with self.assertRaises(ValueError):
            seaweedfs_command("/etc/seaweedfs/s3/s3.json", workspaces=0)

    def test_a_missing_workspace_maximum_is_refused(self):
        with self.assertRaisesRegex(ValueError, WORKSPACE_MAX_KEY):
            seaweedfs_command("/etc/seaweedfs/s3/s3.json", collections=1)

    def test_slots_cover_every_consumer_plus_the_default_collection(self):
        self.assertEqual(volume_slots(0, 0), VOLUME_GROW_BATCH)
        self.assertEqual(volume_slots(54, 0), 55 * VOLUME_GROW_BATCH)

    def test_volume_slots_reserve_one_per_workspace(self):
        for workspaces in (0, 1, 2, 50):
            with self.subTest(workspaces=workspaces):
                self.assertEqual(
                    volume_slots(3, workspaces) - volume_slots(3, 0), workspaces
                )
        command = seaweedfs_command(collections=3, workspaces=50)
        self.assertIn(f"-volume.max={4 * VOLUME_GROW_BATCH + 50}", command)

    def test_slots_accept_the_string_a_jinja_lookup_yields(self):
        self.assertEqual(volume_slots("54", "50"), volume_slots(54, 50))

    def test_the_free_space_floor_clears_a_whole_allocation_unit(self):
        floor_mb = int(min_free_space().removesuffix("MiB"))
        self.assertGreaterEqual(floor_mb, VOLUME_SIZE_LIMIT_MB)
        self.assertEqual(floor_mb, VOLUME_SIZE_LIMIT_MB * MIN_FREE_SPACE_VOLUMES)

    def test_the_volume_size_limit_is_stated_not_inherited(self):
        command = seaweedfs_command(collections=1, workspaces=0)
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
        self.assertIn("-actions Read,Write,WriteAcp,List,Tagging", script)

    def test_keeps_server_in_foreground(self):
        script = seaweedfs_sidecar_script("app", 8333, "AK", "SK")
        self.assertIn("& exec /entrypoint.sh", script)
        self.assertTrue(script.startswith("("))

    def test_contains_no_shell_dollar(self):
        self.assertNotIn("$", seaweedfs_sidecar_script("app", 8333, "AK", "SK"))


class TestSeaweedfsAnonymousDenyPolicyFilter(unittest.TestCase):
    def test_uses_the_only_policy_version_seaweedfs_accepts(self):
        self.assertEqual(seaweedfs_anonymous_deny_policy("b")["Version"], "2012-10-17")

    def test_is_an_explicit_deny_for_every_principal(self):
        statement = _deny()
        self.assertEqual(statement["Effect"], "Deny")
        self.assertEqual(statement["Principal"], "*")

    def test_spares_requests_that_carry_a_signed_username(self):
        self.assertEqual(_deny()["Condition"], {"Null": {"aws:username": "true"}})

    def test_covers_reads_and_listings_but_no_writes(self):
        self.assertEqual(_deny()["Action"], ["s3:Get*", "s3:List*"])

    def test_scopes_the_bucket_and_its_objects(self):
        self.assertEqual(
            _deny("pixelfed")["Resource"],
            ["arn:aws:s3:::pixelfed", "arn:aws:s3:::pixelfed/*"],
        )

    def test_carries_the_sid_the_converge_step_owns(self):
        self.assertEqual(_deny()["Sid"], ANONYMOUS_DENY_SID)

    def test_survives_the_seaweedfs_round_trip_unchanged(self):
        policy = seaweedfs_anonymous_deny_policy("mastodon")
        self.assertEqual(_go_marshal(json.loads(json.dumps(policy))), policy)


class TestSeaweedfsBucketNamesFilter(unittest.TestCase):
    def test_reads_every_listed_bucket(self):
        output = (
            "  mastodon\tsize:0\tlogical:0\tchunk:0\n"
            '  pixelfed\tsize:42\tlogical:40\tchunk:3\towner:"pixelfed"\n'
        )
        self.assertEqual(seaweedfs_bucket_names(output), ["mastodon", "pixelfed"])

    def test_reads_a_bucket_printed_after_the_shell_prompt(self):
        output = "> " + "  mastodon\tsize:0\tlogical:0\tchunk:0\n> "
        self.assertEqual(seaweedfs_bucket_names(output), ["mastodon"])

    def test_a_name_inside_a_longer_one_is_not_listed(self):
        names = seaweedfs_bucket_names("  mastodon-media\tsize:0\tlogical:0\tchunk:0\n")
        self.assertNotIn("mastodon", names)

    def test_an_empty_listing_yields_no_bucket(self):
        self.assertEqual(seaweedfs_bucket_names("> "), [])


class TestSeaweedfsStoredBucketPolicyFilter(unittest.TestCase):
    def test_a_stored_policy_is_returned(self):
        policy = seaweedfs_anonymous_deny_policy("mastodon")
        output = _curl_output(json.dumps(policy, separators=(",", ":")) + "\n", 200)
        self.assertEqual(seaweedfs_stored_bucket_policy(output), policy)

    def test_no_such_bucket_policy_reads_as_no_policy(self):
        output = _curl_output(NO_SUCH_BUCKET_POLICY_XML, 404)
        self.assertEqual(seaweedfs_stored_bucket_policy(output), {})

    def test_a_missing_bucket_is_refused(self):
        output = _curl_output(NO_SUCH_BUCKET_XML, 404)
        self.assertIsNone(seaweedfs_stored_bucket_policy(output))

    def test_access_denied_is_refused(self):
        output = _curl_output("<Error><Code>AccessDenied</Code></Error>", 403)
        self.assertIsNone(seaweedfs_stored_bucket_policy(output))

    def test_a_server_error_is_refused(self):
        output = _curl_output("<Error><Code>InternalError</Code></Error>", 500)
        self.assertIsNone(seaweedfs_stored_bucket_policy(output))

    def test_a_404_without_the_policy_code_is_refused(self):
        self.assertIsNone(seaweedfs_stored_bucket_policy(_curl_output("", 404)))


class TestSeaweedfsBucketPolicyTargetFilter(unittest.TestCase):
    def _policy(self, *statements):
        return {"Version": "2012-10-17", "Statement": list(statements)}

    def test_a_private_bucket_without_policy_gets_the_deny(self):
        self.assertEqual(
            seaweedfs_bucket_policy_target({}, "mastodon", False),
            seaweedfs_anonymous_deny_policy("mastodon"),
        )

    def test_a_private_bucket_with_the_deny_stays_as_stored(self):
        stored = _go_marshal(seaweedfs_anonymous_deny_policy("mastodon"))
        self.assertEqual(
            seaweedfs_bucket_policy_target(stored, "mastodon", False), stored
        )

    def test_a_private_bucket_keeps_a_foreign_statement_next_to_the_deny(self):
        stored = self._policy(FOREIGN_STATEMENT, _deny())
        self.assertEqual(
            seaweedfs_bucket_policy_target(stored, "mastodon", False), stored
        )

    def test_a_private_bucket_with_only_a_foreign_statement_gains_the_deny(self):
        stored = self._policy(FOREIGN_STATEMENT)
        self.assertEqual(
            seaweedfs_bucket_policy_target(stored, "mastodon", False),
            self._policy(FOREIGN_STATEMENT, _deny()),
        )

    def test_a_stale_deny_is_replaced_by_the_current_one(self):
        stale = {**_deny(), "Action": "s3:GetObject"}
        self.assertEqual(
            seaweedfs_bucket_policy_target(self._policy(stale), "mastodon", False),
            self._policy(_deny()),
        )

    def test_a_public_bucket_without_policy_stays_without(self):
        self.assertEqual(seaweedfs_bucket_policy_target({}, "mastodon", True), {})

    def test_a_public_bucket_loses_the_deny(self):
        stored = seaweedfs_anonymous_deny_policy("mastodon")
        self.assertEqual(seaweedfs_bucket_policy_target(stored, "mastodon", True), {})

    def test_a_public_bucket_loses_a_stale_deny_by_its_sid(self):
        stale = {**_deny(), "Action": "s3:GetObject", "Condition": {}}
        self.assertEqual(
            seaweedfs_bucket_policy_target(self._policy(stale), "mastodon", True), {}
        )

    def test_a_public_bucket_keeps_a_foreign_statement(self):
        stored = self._policy(_deny(), FOREIGN_STATEMENT)
        self.assertEqual(
            seaweedfs_bucket_policy_target(stored, "mastodon", True),
            self._policy(FOREIGN_STATEMENT),
        )

    def test_public_must_be_a_bool(self):
        with self.assertRaises(AnsibleFilterError):
            seaweedfs_bucket_policy_target({}, "mastodon", "False")


def _record(workspace, access_key="AK", **overrides):
    return {
        "workspace": workspace,
        "access_key": access_key,
        "secret_key": "SK",
        **overrides,
    }


class TestSeaweedfsWorkspaceNames(unittest.TestCase):
    def test_names_follow_the_workspace_id(self):
        self.assertEqual(
            seaweedfs_workspace(WORKSPACE_A),
            {
                "bucket": f"ws-{WORKSPACE_A}-state",
                "identity": f"ws-{WORKSPACE_A}-provision",
                "file": f"ws-{WORKSPACE_A}.json",
            },
        )

    def test_an_id_that_is_no_lowercase_uuid_is_refused(self):
        for bad in (
            WORKSPACE_A.upper(),
            "ws-1",
            "",
            f"{WORKSPACE_A}/../x",
            f"{WORKSPACE_A} ",
        ):
            with self.subTest(workspace=bad), self.assertRaises(AnsibleFilterError):
                seaweedfs_workspace(bad)


class TestSeaweedfsWorkspaceCredentials(unittest.TestCase):
    def test_new_keys_differ_on_every_call(self):
        first = seaweedfs_workspace_credentials(WORKSPACE_A)
        second = seaweedfs_workspace_credentials(WORKSPACE_A)
        self.assertEqual(set(first), {"workspace", "access_key", "secret_key"})
        self.assertNotEqual(first["access_key"], second["access_key"])
        self.assertNotEqual(first["secret_key"], second["secret_key"])

    def test_keys_carry_no_character_the_signed_curl_splits_on(self):
        record = seaweedfs_workspace_credentials(WORKSPACE_A)
        for field in ("access_key", "secret_key"):
            with self.subTest(field=field):
                self.assertRegex(record[field], r"^[A-Za-z0-9_-]{20,}$")


class TestSeaweedfsWorkspaceIdentity(unittest.TestCase):
    def test_an_identity_holds_read_write_and_list_on_its_bucket_only(self):
        identity = seaweedfs_workspace_identity(_record(WORKSPACE_A))
        bucket = f"ws-{WORKSPACE_A}-state"
        self.assertEqual(identity["name"], f"ws-{WORKSPACE_A}-provision")
        self.assertEqual(
            identity["actions"], [f"Read:{bucket}", f"Write:{bucket}", f"List:{bucket}"]
        )
        self.assertEqual(
            identity["credentials"], [{"accessKey": "AK", "secretKey": "SK"}]
        )

    def test_a_record_with_another_field_is_refused(self):
        with self.assertRaises(AnsibleFilterError):
            seaweedfs_workspace_identity({**_record(WORKSPACE_A), "actions": ["Admin"]})

    def test_a_record_with_an_empty_key_is_refused(self):
        with self.assertRaises(AnsibleFilterError):
            seaweedfs_workspace_identity(_record(WORKSPACE_A, secret_key=""))


class TestSeaweedfsS3Identities(unittest.TestCase):
    def test_workspaces_follow_the_inventory_identities(self):
        document = seaweedfs_s3_identities(
            [ADMIN], [_record(WORKSPACE_B, "B"), _record(WORKSPACE_A, "A")]
        )
        self.assertEqual(
            [identity["name"] for identity in document["identities"]],
            ["admin", f"ws-{WORKSPACE_A}-provision", f"ws-{WORKSPACE_B}-provision"],
        )

    def test_the_admin_alone_is_a_valid_document(self):
        self.assertEqual(seaweedfs_s3_identities([ADMIN], []), {"identities": [ADMIN]})

    def test_an_assembly_without_the_admin_is_refused(self):
        consumer = {**ADMIN, "name": "web-app-nextcloud", "actions": ["Read:nc"]}
        for identities in ([], [consumer], [{**ADMIN, "actions": ["Read"]}]):
            with (
                self.subTest(identities=identities),
                self.assertRaises(AnsibleFilterError),
            ):
                seaweedfs_s3_identities(identities, [_record(WORKSPACE_A)])

    def test_an_admin_without_a_key_is_refused(self):
        with self.assertRaises(AnsibleFilterError):
            seaweedfs_s3_identities([{**ADMIN, "credentials": []}], [])

    def test_a_repeated_identity_name_is_refused(self):
        with self.assertRaises(AnsibleFilterError):
            seaweedfs_s3_identities(
                [ADMIN], [_record(WORKSPACE_A, "A"), _record(WORKSPACE_A, "B")]
            )

    def test_a_shared_access_key_is_refused_without_naming_it(self):
        with self.assertRaises(AnsibleFilterError) as caught:
            seaweedfs_s3_identities([ADMIN], [_record(WORKSPACE_A, "admin-ak")])
        self.assertNotIn("admin-ak", str(caught.exception))


class TestSeaweedfsWorkspaceSlot(unittest.TestCase):
    def test_a_free_slot_admits_a_new_workspace(self):
        self.assertTrue(
            seaweedfs_workspace_slot([f"ws-{WORKSPACE_B}.json"], WORKSPACE_A, 2)
        )

    def test_a_workspace_beyond_the_maximum_is_refused_naming_the_key(self):
        with self.assertRaisesRegex(AnsibleFilterError, WORKSPACE_MAX_KEY):
            seaweedfs_workspace_slot([f"ws-{WORKSPACE_B}.json"], WORKSPACE_A, 1)

    def test_a_workspace_that_holds_a_slot_stays_when_all_are_taken(self):
        self.assertTrue(
            seaweedfs_workspace_slot([f"ws-{WORKSPACE_A}.json"], WORKSPACE_A, 1)
        )

    def test_a_stray_file_name_is_refused(self):
        with self.assertRaises(AnsibleFilterError):
            seaweedfs_workspace_slot(["ws-notes.json"], WORKSPACE_A, 5)

    def test_a_boolean_maximum_is_refused(self):
        with self.assertRaises(AnsibleFilterError):
            seaweedfs_workspace_slot([], WORKSPACE_A, True)


FILER_CONF = """> {
  "version": 0,
  "locations": [
    {
      "locationPrefix": "/buckets/ws-",
      "volumeGrowthCount": 1
    }
  ]
}
> """


class TestSeaweedfsLocationConfigured(unittest.TestCase):
    def test_the_rule_is_found(self):
        self.assertTrue(seaweedfs_location_configured(FILER_CONF, "/buckets/ws-", 1))

    def test_another_growth_count_is_not_the_rule(self):
        self.assertFalse(seaweedfs_location_configured(FILER_CONF, "/buckets/ws-", 7))

    def test_an_empty_configuration_holds_no_rule(self):
        self.assertFalse(seaweedfs_location_configured("> {}\n> ", "/buckets/ws-", 1))

    def test_output_without_a_configuration_is_refused(self):
        with self.assertRaises(AnsibleFilterError):
            seaweedfs_location_configured("> error\n> ", "/buckets/ws-", 1)


VERSIONING_ENABLED = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<VersioningConfiguration xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
    "<Status>Enabled</Status></VersioningConfiguration>"
)
VERSIONING_NEVER = (
    '<VersioningConfiguration xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
    "</VersioningConfiguration>"
)


class TestSeaweedfsVersioningEnabled(unittest.TestCase):
    def test_enabled_is_read(self):
        self.assertTrue(
            seaweedfs_versioning_enabled(_curl_output(VERSIONING_ENABLED, 200))
        )

    def test_a_bucket_that_never_versioned_is_not_enabled(self):
        self.assertFalse(
            seaweedfs_versioning_enabled(_curl_output(VERSIONING_NEVER, 200))
        )

    def test_suspended_is_not_enabled(self):
        suspended = VERSIONING_ENABLED.replace("Enabled", "Suspended")
        self.assertFalse(seaweedfs_versioning_enabled(_curl_output(suspended, 200)))

    def test_a_missing_bucket_is_refused(self):
        with self.assertRaises(AnsibleFilterError):
            seaweedfs_versioning_enabled(_curl_output(NO_SUCH_BUCKET_XML, 404))

    def test_access_denied_is_refused(self):
        with self.assertRaises(AnsibleFilterError):
            seaweedfs_versioning_enabled(_curl_output("<Error/>", 403))


def _listing(*keys, truncated=False):
    contents = "".join(f"<Contents><Key>{key}</Key></Contents>" for key in keys)
    return (
        "<ListBucketResult><Name>b</Name>"
        f"<IsTruncated>{'true' if truncated else 'false'}</IsTruncated>"
        f"{contents}</ListBucketResult>"
    )


class TestSeaweedfsBucketStateFiles(unittest.TestCase):
    def test_state_files_are_named(self):
        output = _curl_output(_listing("SO1/1.tfstate", "SO1/1.tflock", "x"), 200)
        self.assertEqual(seaweedfs_bucket_state_files(output), ["SO1/1.tfstate"])

    def test_an_empty_bucket_holds_none(self):
        self.assertEqual(
            seaweedfs_bucket_state_files(_curl_output(_listing(), 200)), []
        )

    def test_a_missing_bucket_holds_none(self):
        output = _curl_output(NO_SUCH_BUCKET_XML, 404)
        self.assertEqual(seaweedfs_bucket_state_files(output), [])

    def test_a_truncated_listing_is_refused(self):
        output = _curl_output(_listing("a", truncated=True), 200)
        with self.assertRaises(AnsibleFilterError):
            seaweedfs_bucket_state_files(output)

    def test_a_404_without_no_such_bucket_is_refused(self):
        with self.assertRaises(AnsibleFilterError):
            seaweedfs_bucket_state_files(_curl_output("", 404))

    def test_access_denied_is_refused(self):
        with self.assertRaises(AnsibleFilterError):
            seaweedfs_bucket_state_files(_curl_output("<Error/>", 403))


if __name__ == "__main__":
    unittest.main()
