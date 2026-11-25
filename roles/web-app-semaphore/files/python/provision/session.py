from __future__ import annotations

import contextlib
import json
import re
import sys
from pathlib import Path

from provision import inputs, provider_env, remote, sandbox
from provision.dns import resolver
from provision.opentofu import LOCK_ID, FailedError, tofu

PACKAGE = Path(__file__).resolve().parent
OPENTOFU = PACKAGE.parent.with_name("opentofu")
STATE_REGION = "us-east-1"
CLEARED_PREFIXES = ("TF_", "AWS_")
CLEARED_NAMES = frozenset({"BAO_TOKEN", "VAULT_TOKEN", "SEMAPHORE_JWT"})
SESSION_NAMES = frozenset(
    {
        "HOME",
        "TMPDIR",
        "TF_IN_AUTOMATION",
        "TF_INPUT",
        "TF_CLI_CONFIG_FILE",
        "TF_ENCRYPTION",
        "BAO_ADDR",
        "BAO_TOKEN",
        "BAO_CACERT",
    }
)
BACKEND_FILE = "backend.tfbackend"
VALUES_FILE = "values.tfvars.json"
RESOLV_CONF = Path("/etc/resolv.conf")
SNAPSHOT_RECORD = "platform/data/provision/transit/{workspace}"
TRANSIT_POLICY = "{workspace}-transit"
TRANSIT_ROLE = "{workspace}-transit-child"
SNAPSHOT_FIELDS = ("key_created_at", "snapshot_at")
ENDPOINTS = frozenset({"endpoint", "auth_url"})
ENDPOINT_TEMPLATES = frozenset({"{host}"})
WORKSPACE_NAME = re.compile(r"^ws-[a-z0-9-]+$")


def credential_names(credentials):
    """Args:
        credentials: the decoded ``credentials.json``.

    Returns:
        Every environment name a provider or DNS module reads its credential
        from, cleared before the task's own values are set.
    """
    names = set(credentials["zone"]["env"])
    for entry in credentials["dns"].values():
        names |= set(entry["env"])
    for provider in credentials["providers"].values():
        names |= set(provider["env"])
        workspace_secrets = provider.get(provider_env.WORKSPACE_SECRETS, [])
        for secret in provider["secrets"] + workspace_secrets:
            names |= set(secret.get("env", {}))
            names |= set(secret.get(provider_env.CATALOG, {}))
    return names


def credential_file_names(credentials):
    """Args:
        credentials: the decoded ``credentials.json``.

    Returns:
        Every environment name a provider reads a path below its task's
        ``credentials`` directory from.
    """
    return frozenset(
        name
        for provider in credentials["providers"].values()
        for name, value in provider["env"].items()
        if "{credentials}" in value
    )


def endpoint_names(credentials):
    """Args:
        credentials: the decoded ``credentials.json``.

    Returns:
        Every environment name a provider reads the address of its API from,
        or the remote naming it, such as ``INCUS_REMOTE``.
    """
    names = set()
    for provider in credentials["providers"].values():
        names |= {
            name
            for name, value in provider["env"].items()
            if value in ENDPOINT_TEMPLATES
        }
        workspace_secrets = provider.get(provider_env.WORKSPACE_SECRETS, [])
        for secret in provider["secrets"] + workspace_secrets:
            fields = secret.get("env", {}) | secret.get(provider_env.CATALOG, {})
            names |= {name for name, field in fields.items() if field in ENDPOINTS}
    return frozenset(names)


def is_encryption(value):
    """Args:
        value: a ``TF_ENCRYPTION`` a run passes.

    Returns:
        Whether it is exactly what :func:`encryption` writes for one
        workspace, so its key provider is the workspace's transit key behind
        the pinned ``BAO_ADDR`` and nothing else.
    """
    try:
        document = json.loads(value)
        key = document["key_provider"]["openbao"]["workspace"]["key_name"]
    except (ValueError, TypeError, KeyError):
        return False
    workspace = str(key).removesuffix("-provision")
    return WORKSPACE_NAME.match(workspace) is not None and document == json.loads(
        encryption(workspace)
    )


def tofu_names(credentials):
    """Args:
        credentials: the decoded ``credentials.json``.

    Returns:
        Every environment name :attr:`Session.environment` may hand to
        ``tofu``; the spawner refuses a run with any other.
    """
    return sandbox.PASSED | SESSION_NAMES | credential_names(credentials)


def _hcl(value):
    return json.dumps(value).replace("${", "$${").replace("%{", "%%{")


def write_backend(task, config, bucket, key, keys):
    values = {
        "bucket": bucket,
        "key": key,
        "region": STATE_REGION,
        "access_key": keys["access_key"],
        "secret_key": keys["secret_key"],
    }
    if config["cafile"]:
        values["custom_ca_bundle"] = config["cafile"]
    text = "".join(f"{name} = {_hcl(value)}\n" for name, value in values.items())
    text += f"endpoints = {{\n  s3 = {_hcl(config['state'])}\n}}\n"
    return sandbox.task_write(task, BACKEND_FILE, text)


def encryption(workspace):
    method = "${method.aes_gcm.workspace}"
    return json.dumps(
        {
            "key_provider": {
                "openbao": {
                    "workspace": {
                        "key_name": f"{workspace}-provision",
                        "transit_engine_path": "/transit",
                        "key_length": 32,
                    }
                }
            },
            "method": {
                "aes_gcm": {"workspace": {"keys": "${key_provider.openbao.workspace}"}}
            },
            "state": {"method": method, "enforced": True},
            "plan": {"method": method, "enforced": True},
        }
    )


def require_snapshot(bao, workspace):
    """Args:
        bao: the logged-in OpenBao client of the task.
        workspace: ``ws-<id>``.

    Raises:
        RefusedError: the transit key of the workspace has no snapshot
            record, or its snapshot is older than the key.
    """
    path = SNAPSHOT_RECORD.format(workspace=workspace)
    record = bao.record(path) or {}
    try:
        created, snapshot = (int(str(record[name])) for name in SNAPSHOT_FIELDS)
    except (KeyError, ValueError):
        raise inputs.RefusedError(
            f"{path} holds no key_created_at and snapshot_at, so the transit key "
            f"{workspace}-provision has no backup"
        ) from None
    if snapshot < created:
        raise inputs.RefusedError(
            f"the snapshot in {path} predates the transit key {workspace}-provision"
        )


@contextlib.contextmanager
def opened(env, config, credentials, workspace, task, key, role):
    """Args:
        env, config, credentials, workspace, task, key: as for :class:`Session`.
        role: the suffix of the workspace's task token role the run logs in
            with once: ``provision-<provider>`` for the provision and destroy
            templates, which pin the provider, ``provision`` for unlock and
            dns, ``zone`` for zone.

    Returns:
        A :class:`Session` on the logged-in role token, which OpenBao revokes
        with every child of it on every exit of the block Python handles; a
        SIGKILL leaves the role token until its ``token_ttl`` and the child
        until :data:`provider_env.RUN_BUDGET`.
    """
    bao = remote.OpenBao(config["openbao"], config["cafile"])
    bao.login(f"{workspace['workspace']}-{role}", inputs.required(env, "SEMAPHORE_JWT"))
    try:
        yield Session(bao, env, config, credentials, workspace, task, key)
    except BaseException:
        revoke_after_failure(bao)
        raise
    with remote.alarm_deferred():
        bao.revoke()


def revoke_after_failure(bao):
    """Args:
        bao: the OpenBao client of a run whose block raised.

    Returns:
        Once OpenBao revoked its role token, or once stderr names the error
        the revoke or its deferred budget alarm raised, so the exception of
        the block stays the one the run ends with; a SystemExit or
        KeyboardInterrupt during the revoke still ends the run.
    """
    try:
        with remote.alarm_deferred():
            bao.revoke()
    except Exception as failure:
        print(
            f"the revoke of the role token after the run's own error: {failure}",
            file=sys.stderr,
        )


class Session:
    """Args:
    bao: the OpenBao client, logged in with the run's role token.
    env: the task environment.
    config: the result of :func:`configuration`.
    credentials: the decoded ``credentials.json``.
    workspace: the ``workspace.json`` document.
    task: the task directory holding the staged root.
    key: the state key in the workspace bucket.
    """

    def __init__(self, bao, env, config, credentials, workspace, task, key):
        self.workspace = workspace["workspace"]
        self.zone = workspace["dns"]["zone"]
        self.bucket_name = f"{self.workspace}-state"
        self.key = key
        self.task = task
        self.config = config
        self.env = env
        self.credentials = credentials
        self.bao = bao
        state = credentials["state"]
        keys = provider_env.mapped(
            self.bao, state["path"].format(workspace=self.workspace), state["backend"]
        )
        self.bucket = remote.StateBucket(
            config["state"],
            keys["access_key"],
            keys["secret_key"],
            STATE_REGION,
            config["cafile"],
        )
        self.backend = write_backend(task, config, self.bucket_name, key, keys)
        self.reached = {}
        self.environment = {}

    def open(self, reach):
        """Args:
            reach: the ``{path, env}`` entry of ``credentials.json`` whose
                fields the root's provider reads from the environment.

        Returns:
            The session, once it read that credential and set the environment
            of every OpenTofu call: ``BAO_TOKEN`` there is a child token of
            the token role ``ws-<id>-transit-child`` that carries
            ``ws-<id>-transit`` alone, the transit key of the workspace's
            state, never the role token of the run.
        """
        self.reached = provider_env.mapped(
            self.bao,
            reach["path"].format(workspace=self.workspace, zone=self.zone),
            reach["env"],
        )
        transit = self.bao.child(
            TRANSIT_ROLE.format(workspace=self.workspace),
            TRANSIT_POLICY.format(workspace=self.workspace),
            f"{int(provider_env.RUN_BUDGET.total_seconds())}s",
        )
        cleared = credential_names(self.credentials)
        self.environment = {
            name: value
            for name, value in self.env.items()
            if name in sandbox.PASSED
            and not name.startswith(CLEARED_PREFIXES)
            and name not in cleared
            and name not in CLEARED_NAMES
        } | {
            "HOME": str(sandbox.home_of(self.task)),
            "TMPDIR": str(sandbox.home_of(self.task)),
            "TF_IN_AUTOMATION": "1",
            "TF_INPUT": "0",
            "TF_CLI_CONFIG_FILE": str(OPENTOFU / "tofurc"),
            "TF_ENCRYPTION": encryption(self.workspace),
            "BAO_ADDR": self.config["openbao"],
            "BAO_TOKEN": transit,
            **self.reached,
        }
        if self.config["cafile"]:
            self.environment["BAO_CACERT"] = self.config["cafile"]
        return self

    def add_provider(self, provider, spec, region, source):
        context = {
            "workspace": self.workspace,
            "zone": self.zone,
            "host": str(region.get("host", "")),
            "provider": provider,
        }
        self.environment |= provider_env.provider_environment(
            self.bao, spec, context, self.task, source, region
        )

    def run(self, *arguments, capture=False):
        return tofu(self.task, self.environment, *arguments, capture=capture)

    def init(self):
        self.run("init", "-input=false", f"-backend-config={self.backend}")

    def addresses(self):
        if not self.bucket.exists(self.bucket_name, self.key):
            return []
        return self.run("state", "list", capture=True).split()

    def empty(self):
        return not self.addresses()

    def servers(self):
        if self.config["flavor"] == "knot":
            return [
                (self.reached["DNS_UPDATE_SERVER"], self.reached["DNS_UPDATE_PORT"])
            ]
        return resolver.zone_servers(self.zone, RESOLV_CONF)

    def refuse_taken(self, label):
        fqdn = f"{label}.{self.workspace}.{self.zone}"
        if resolver.taken(fqdn, self.servers()):
            raise inputs.RefusedError(
                f"{fqdn} already holds an A, AAAA or CNAME record"
            )

    def outputs(self):
        """Returns:
        ``{output name: value}`` the state holds, read without a write.
        """
        outputs = json.loads(self.run("output", "-json", capture=True))
        return {name: output["value"] for name, output in outputs.items()}

    def apply(self, unclaimed, record=None):
        """Args:
            unclaimed: called before the apply of an empty state; it raises
                :class:`inputs.RefusedError` for a name someone else holds.
            record: ``(key, document)`` written to the state bucket right
                before the apply, None for none.

        Returns:
            ``{output name: value}`` of the root.
        """
        require_snapshot(self.bao, self.workspace)
        if self.empty():
            unclaimed()
        if record is not None:
            key, document = record
            self.bucket.put(self.bucket_name, key, json.dumps(document).encode())
        self.run("apply", "-auto-approve", "-input=false", f"-var-file={VALUES_FILE}")
        return self.outputs()

    def destroy(self, *kept_with_state):
        """Args:
            kept_with_state: further keys deleted together with the state.

        Returns:
            ``{"destroyed": [resource address], "state": "deleted"}``.
        """
        require_snapshot(self.bao, self.workspace)
        destroyed = self.addresses()
        self.run("destroy", "-auto-approve", "-input=false", f"-var-file={VALUES_FILE}")
        if self.addresses():
            raise FailedError(f"{self.key} still holds resources after tofu destroy")
        return self.forget(destroyed, *kept_with_state)

    def holds_nothing(self, *records):
        """Args:
            records: further keys that would name something to destroy.

        Returns:
            Whether neither the state nor any of *records* exists.
        """
        return not any(
            self.bucket.exists(self.bucket_name, key) for key in (self.key, *records)
        )

    def forget(self, destroyed=(), *kept_with_state):
        """Args:
            destroyed: the resource addresses the destroy removed.
            kept_with_state: further keys deleted together with the state.

        Returns:
            ``{"destroyed": [resource address], "state": "deleted"}`` once the
            state and its lock are deleted.
        """
        for key in (self.key, f"{self.key}.tflock", *kept_with_state):
            self.bucket.delete(self.bucket_name, key)
        if self.bucket.exists(self.bucket_name, self.key):
            raise FailedError(f"{self.bucket_name}/{self.key} survived its delete")
        return {"destroyed": list(destroyed), "state": "deleted"}

    def unlock(self):
        lock = self.bucket.get(self.bucket_name, f"{self.key}.tflock")
        if lock is None:
            print(f"{self.key} holds no lock")
            return
        lock_id = str(json.loads(lock).get("ID", ""))
        if not LOCK_ID.match(lock_id):
            raise FailedError(f"the lock of {self.key} carries no lock id")
        self.run("force-unlock", "-force", lock_id)
