from __future__ import annotations

import re
import unittest

from utils.cache.files import PROJECT_ROOT, read_text

README = PROJECT_ROOT / "roles" / "web-app-semaphore" / "README.md"
BLOCK = re.MULTILINE | re.DOTALL
RUNNER_KINDS = (
    "`app-control`",
    "`deploy`",
    "`workspaces`",
    "`provision`",
    "`export`",
    "`ws-<id>`",
)
LOCKED_FIELDS = (
    "allow_override_args_in_task",
    "allow_override_branch_in_task",
    "allow_parallel_tasks",
    "allow_override_inventory",
    "jwt_params",
    "SEMAPHORE_JWT_ENABLED=true",
    "SEMAPHORE_JWT_ISSUER",
    "`v2.20.1`",
    "`SALES_ORDER`, `LINE`, `HOST`, `HOST_KEY`, `ROLES`, `DNS_LABEL` and `INVENTORY_COMMIT`",
)
CONTRACT = (
    "**Inputs:**",
    "**Idempotent apply:**",
    "counts a resource that is already gone as removed",
    "`project_id`, `template_id`, `repository_id`, `inventory_id`, `environment_id`, `git_url`, `git_branch`, `ssh_key_id`, `runner_tag`, `app`, `playbook`, `arguments` (decoded), `survey_variables` (the sorted survey variable names) and `environment_variables`",
    "`workspace_dns`",
    "`workspace_semaphore`",
)
WORKSPACE_VALUES = (
    "`workspace.json`",
    "`WORKSPACE_DNS_ZONE`",
    "`WORKSPACE_DNS_ZONE_ID`",
    "`WORKSPACE_TARGETS`",
    "`INVITE_KEY`",
    "`INVENTORY_COMMIT`",
    "`HOST_KEY`",
    "`private_targets`",
)
INVENTORY_COMMIT = (
    "`INVENTORY_COMMIT`",
    "40 lowercase hex digits",
    "`git merge-base --is-ancestor` against `origin/main`",
    "The store protects `main`",
)
USAGE = (
    "**Usage template:**",
    "with no survey and no argument, and one active daily schedule",
    "`credentials.usage_client_secret` with the task's own OpenBao token",
    "reported with `active_users` null and gets no call",
    "`workspace`, `counted_at` (UTC, ISO 8601) and `hosts`, a list of `{host, realm, active_users}`",
)
STORE_CREDENTIALS = (
    "**Store credentials:**",
    "`rotate store credentials`",
    "carries no template grant",
    "`0 4 * * 1`",
    "`platform/data/store/semaphore` and `platform/data/store/gitea` and nothing else",
    "exactly the two fields `token` and `expires_at`",
    "Semaphore's own `expires_at` 30 days after the run",
    "and no other",
    "No token reaches an argument, the task output or a Semaphore environment",
)
EXPORT_BOUNDS = (
    "is below `2`, or is not below `services.keycloak.events.admin.expiration_days`"
)
EXPORT_ANNOUNCEMENT = (
    "naming the new Owner, the join time and the first day an export for them"
)
EXPORT = (
    "**Export:**",
    "`export ws-<id>`",
    "exactly `WORKSPACE` and `EXPORT_FOR`",
    "`SEMAPHORE_EXPORT_VARIABLES`, none of them a secret",
    "Keycloak attribute `export_recipient`",
    "it takes no recipient from the survey or the environment",
    "`platform/data/export/owners/ws-<id>`",
    "no direct member of that group id",
    "`ORGANIZATION_GROUP_MEMBERSHIP`",
    "`services.semaphore.workspaces.export.owner_min_age_days` (default `7`)",
    EXPORT_BOUNDS,
    "`secrets.kdbx`",
    "`passphrase.age`",
    "`age -r <recipient>`",
    "valid for 900 seconds",
    "mails every direct member of the pinned group",
    "`announce owners` runs",
    "daily at `0 6 * * *`",
    "with the roles `announce-owners` and `prune-exports`",
    "with the policy `export-shared` only",
    "lists `platform/metadata/export/owners/`",
    EXPORT_ANNOUNCEMENT,
    "It keeps no state",
    "a subgroup member or a group found by name never counts",
    "`prune exports` runs",
    "deletes every object older than one hour",
    "A leaked store credential can start an export for any Owner of any workspace",
    "every Owner is mailed daily about that account until the window ends",
)


def section(title):
    """Args:
        title: a ``##`` heading of the README.

    Returns:
        The text below it up to the next ``##`` heading.
    """
    text = read_text(str(README))
    match = re.search(rf"^## {re.escape(title)}\n(.*?)(?=^## )", text, BLOCK)
    assert match, f"the README has no section {title}"
    return match.group(1)


def item(title):
    """Args:
        title: the bold label of a list item in the Provision section.

    Returns:
        The text of that item.
    """
    text = section("Provision")
    match = re.search(
        rf"^- \*\*{re.escape(title)}:\*\*\n(.*?)(?=^- \*\*|\Z)", text, BLOCK
    )
    assert match, f"the Provision section has no item {title}"
    return match.group(1)


class TestProvisionReadme(unittest.TestCase):
    def assert_names(self, text, *phrases):
        for phrase in phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

    def test_the_readme_names_the_provision_contract(self):
        self.assert_names(
            section("Provision"),
            "`guest`",
            "`CanRunProjectTasks` and `CanReadProject`",
            "no provision output carries a secret",
        )
        self.assert_names(
            item("Interface"), "interface.json", "`dns_label`", "`host_key`"
        )
        self.assert_names(
            item("Order line"),
            "`^[A-Za-z][A-Za-z0-9-]{0,55}$`",
            "`^[1-9][0-9]{0,5}$`",
            "`7` and `007` cannot name the same line twice",
            "`*.tf`, `*.tf.json`, `*.tofu`, `*.tofu.json`, `.terraformrc` or `.tofurc`",
            "`TF_*`",
        )
        self.assert_names(
            item("State"),
            "`<SALES_ORDER>/<LINE>.tfstate`",
            "`use_lockfile = true`",
            "`enforced = true`",
            "`platform/data/provision/transit/ws-<id>`",
            "the snapshot is older than the key",
        )
        self.assert_names(
            item("Unlock"), "`unlock ws-<id>`", "`tofu force-unlock -force`"
        )
        self.assert_names(item("DNS flavors"), "`knot`", "`route53`", "`cloudflare`")

    def test_the_readme_states_the_cloudflare_reach(self):
        self.assert_names(
            item("DNS flavors"),
            "A zone token changes every record of its zone and so reaches every "
            "workspace placed in that zone",
            "no two zones share a token",
        )

    def test_the_readme_names_the_byo_record(self):
        self.assert_names(
            item("Bring-your-own record"),
            "`dns ws-<id>`",
            "`create`, `remove` or `unlock`",
            "`HOST` and `DNS_LABEL`",
            "`<SALES_ORDER>/<LINE>.dns.tfstate`",
            "already holds an A, AAAA or CNAME record",
            "a removal deletes only its own record",
            "a CNAME to that name",
            "never resolves it",
        )

    def test_the_readme_names_the_dns_credentials(self):
        self.assert_names(
            item("DNS flavors"),
            "never `services.*`",
            "`secrets.credentials.route53_access_key_id`",
            "`secrets.credentials.cloudflare_zone_tokens`",
            "`platform/data/workspaces/route53`",
            "`platform/data/provision/cloudflare/<zone>`",
            "no value reaches an argument or a log",
            "A credential placed under `services.*` is ignored",
        )

    def test_the_readme_names_the_catalog(self):
        self.assert_names(
            item("Catalog"),
            "`services.semaphore.workspaces.catalog.<provider>`",
            "`$defs.catalog`",
            "replaces the catalog of a provider as a whole",
            "The defaults of `incus` and `proxmox`",
            "The defaults of `hetzner`, `ionos` and `scs` are empty",
            "sets its own catalog",
            "Region keys must be unique across providers",
        )

    def test_the_readme_names_the_backend_keys(self):
        self.assert_names(
            item("Backend keys"),
            "`tenant/data/ws-<id>-provision/s3`",
            "mode `0600`",
            "the only `-backend-config` argument",
            "never enter the environment or an argument",
        )

    def test_the_readme_states_the_route53_reach(self):
        text = item("DNS flavors")
        self.assert_names(
            text,
            "exactly four actions",
            "`route53:ChangeResourceRecordSets`",
            "`route53:GetHostedZone`",
            "`route53:ListResourceRecordSets`",
            "`route53:GetChange`",
            "lists every record of the subzone",
        )


def missing(text, phrases):
    return [phrase for phrase in phrases if phrase not in text]


class TestReadme(unittest.TestCase):
    def setUp(self):
        self.text = read_text(str(README))

    def test_the_readme_names_every_runner_kind(self):
        self.assertEqual(missing(self.text, RUNNER_KINDS), [])

    def test_the_readme_names_the_locked_fields(self):
        self.assertEqual(missing(self.text, LOCKED_FIELDS), [])

    def test_the_readme_holds_the_workspace_task_contract(self):
        self.assertEqual(missing(self.text, CONTRACT), [])

    def test_the_readme_names_the_workspace_values(self):
        self.assertEqual(missing(self.text, WORKSPACE_VALUES), [])

    def test_the_readme_names_the_inventory_commit(self):
        self.assertEqual(missing(self.text, INVENTORY_COMMIT), [])

    def test_the_readme_names_the_usage_template(self):
        self.assertEqual(missing(self.text, USAGE), [])

    def test_negative_control_a_dropped_usage_rule_is_reported(self):
        planted = self.text.replace(
            "reported with `active_users` null and gets no call", ""
        )
        self.assertEqual(
            missing(planted, USAGE),
            ["reported with `active_users` null and gets no call"],
        )

    def test_the_readme_names_the_store_credentials_rotation(self):
        self.assertEqual(missing(section("Workspaces"), STORE_CREDENTIALS), [])

    def test_negative_control_a_dropped_rotation_rule_is_reported(self):
        planted = section("Workspaces").replace("carries no template grant", "")
        self.assertEqual(
            missing(planted, STORE_CREDENTIALS), ["carries no template grant"]
        )

    def test_the_readme_names_the_export(self):
        self.assertEqual(missing(section("Workspaces"), EXPORT), [])

    def test_negative_control_a_dropped_export_bound_is_reported(self):
        planted = section("Workspaces").replace("is below `2`, or ", "")
        self.assertEqual(missing(planted, EXPORT), [EXPORT_BOUNDS])

    def test_negative_control_a_dropped_announcement_field_is_reported(self):
        planted = section("Workspaces").replace("the join time and ", "")
        self.assertEqual(missing(planted, EXPORT), [EXPORT_ANNOUNCEMENT])

    def test_negative_control_a_dropped_contract_rule_is_reported(self):
        planted = self.text.replace("**Idempotent apply:**", "")
        self.assertEqual(missing(planted, CONTRACT), ["**Idempotent apply:**"])


if __name__ == "__main__":
    unittest.main()
