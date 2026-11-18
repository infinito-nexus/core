from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from provision import inputs, provider_env, remote

HERE = Path(__file__).resolve().parent
OPENTOFU = HERE.parent / "opentofu"
TEMPLATES = ("provision", "destroy", "unlock", "dns")
STATE_REGION = "us-east-1"
CLEARED_PREFIXES = ("TF_", "AWS_")
CLEARED_NAMES = frozenset({"BAO_TOKEN", "VAULT_TOKEN", "SEMAPHORE_JWT"})
BACKEND_FILE = "backend.tfbackend"
VALUES_FILE = "values.tfvars.json"
RESOLV_CONF = Path("/etc/resolv.conf")
SNAPSHOT_RECORD = "platform/data/provision/transit/{workspace}"
SNAPSHOT_FIELDS = ("key_created_at", "snapshot_at")
LOCKS = "provision-locks"
LOCK_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
RECORD = "{sales_order}/{line}.provision.json"
SUPERVISOR = HERE / "tofu_supervisor.py"
GROUP_POLL_SECONDS = 0.1


class FailedError(Exception):
    """Args:
    message: the step that failed, never a credential.
    """


class BudgetError(FailedError):
    """Args:
    message: the budget the run outlived and how OpenTofu stopped.
    """


def configuration(env):
    """Args:
        env: the environment of the provision runner and the template.

    Returns:
        The OpenBao origin, the optional CA file, the state endpoint, the
        catalog mount and the DNS flavor of the deployment.
    """
    flavor = inputs.required(env, "PROVISION_DNS_FLAVOR")
    if flavor not in inputs.DNS_FLAVORS:
        raise inputs.RefusedError(f"PROVISION_DNS_FLAVOR {flavor!r} is no DNS flavor")
    return {
        "openbao": inputs.required(env, "BAO_ADDR"),
        "cafile": env.get("PROVISION_CA_FILE", ""),
        "state": inputs.required(env, "PROVISION_STATE_ENDPOINT"),
        "catalogs": inputs.required(env, "PROVISION_CATALOG_DIR"),
        "flavor": flavor,
    }


def credential_names(credentials):
    """Args:
        credentials: the decoded ``credentials.json``.

    Returns:
        Every environment name a provider or DNS module reads its credential
        from, cleared before the task's own values are set.
    """
    names = set()
    for entry in credentials["dns"].values():
        names |= set(entry["env"])
    for provider in credentials["providers"].values():
        names |= set(provider["env"])
        workspace_secrets = provider.get(provider_env.WORKSPACE_SECRETS, [])
        for secret in provider["secrets"] + workspace_secrets:
            names |= set(secret.get("env", {}))
            names |= set(secret.get(provider_env.CATALOG, {}))
    return names


@contextlib.contextmanager
def task_directory():
    path = Path(tempfile.mkdtemp(prefix="provision-task-"))
    try:
        yield path
    finally:
        with remote.alarm_deferred():
            shutil.rmtree(path, ignore_errors=True)


@contextlib.contextmanager
def workspace_lock(workspace, exclusive):
    directory = Path(tempfile.gettempdir()) / LOCKS
    directory.mkdir(mode=0o700, exist_ok=True)
    mode = (fcntl.LOCK_EX | fcntl.LOCK_NB) if exclusive else fcntl.LOCK_SH
    with (directory / f"{workspace}.lock").open("a", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle, mode)
        except BlockingIOError:
            raise inputs.RefusedError(
                f"a provision or destroy task of {workspace} is running"
            ) from None
        yield


def stage(task, root, flavor, workspace):
    shutil.copytree(
        root,
        task,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("catalog.json", "workspace.json", ".terraform"),
    )
    shutil.copytree(OPENTOFU / "modules" / f"dns-{flavor}", task / "modules" / "dns")
    (task / "workspace.json").write_text(json.dumps(workspace), encoding="utf-8")


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
    return provider_env.private_file(task / BACKEND_FILE, text)


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


def _ended(process, deadline=None):
    """Args:
        process: the :data:`SUPERVISOR` to wait for, left unreaped so its
            zombie keeps the id of its process group reserved for
            :func:`_killed`.
        deadline: the :func:`time.monotonic` bound of the wait, ``None`` for
            none.

    Returns:
        Its exit code, negative for the signal that killed it, or ``None``
        once the deadline passed first.
    """
    flags = os.WEXITED | os.WNOWAIT | (0 if deadline is None else os.WNOHANG)
    while (info := os.waitid(os.P_PID, process.pid, flags)) is None:
        if time.monotonic() >= deadline:
            return None
        time.sleep(GROUP_POLL_SECONDS)
    return info.si_status if info.si_code == os.CLD_EXITED else -info.si_status


def _unwatched(process, deadline):
    """Args:
    process: a :data:`SUPERVISOR` a signal killed, so the rest of its
        process group, ``tofu`` included, runs on unwatched. It is reaped
        first, as its zombie would count as a member; the members that
        still run keep the group id reserved. Returns once the group is
        empty or ``deadline``, a :func:`time.monotonic` value, passed.
    """
    process.wait()
    while time.monotonic() < deadline:
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            return
        time.sleep(GROUP_POLL_SECONDS)


def _stopped(process, command):
    """Args:
        process: the :data:`SUPERVISOR` of the running ``tofu`` to stop.
        command: its subcommand, e.g. ``apply``.

    Returns:
        How ``tofu`` ended: on SIGINT within :data:`provider_env.TOFU_GRACE`,
        or killed after it, also when its supervisor died; the caller kills.

    Raises:
        Whatever a signal handler raises during the grace.
    """
    signal.alarm(0)
    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGINT)
    grace = provider_env.TOFU_GRACE
    deadline = time.monotonic() + grace.total_seconds()
    code = _ended(process, deadline)
    if code is None:
        return (
            f"tofu {command} ignored SIGINT for {grace} and was killed, so its "
            f"state may miss resources and keep its lock until unlock runs"
        )
    if code < 0:
        _unwatched(process, deadline)
        return (
            f"the supervisor of tofu {command} died with {code}, so its process "
            f"group got SIGINT and up to {grace} before SIGKILL, and the state "
            f"of tofu may miss resources and keep its lock until unlock runs"
        )
    return f"tofu {command} stopped on SIGINT with exit code {code}"


def _killed(process):
    """Args:
    process: the :data:`SUPERVISOR` whose process group, ``tofu`` and its
        provider plugins included, gets SIGKILL and is reaped; the group id
        stays reserved while any member lives, the unreaped supervisor too.
    """
    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGKILL)
    process.wait()


def tofu(task, environment, *arguments, capture=False):
    command = arguments[0]
    with subprocess.Popen(
        [sys.executable, "-I", str(SUPERVISOR), str(os.getpid()), "tofu", *arguments],
        cwd=task,
        env=environment,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        start_new_session=True,
    ) as process:
        try:
            output = process.stdout.read() if capture else ""
            code = _ended(process)
        except BaseException as stop:
            stopped = _stopped(process, command)
            if isinstance(stop, BudgetError):
                raise BudgetError(f"{stop}; {stopped}") from None
            raise
        else:
            if code < 0:
                raise FailedError(_stopped(process, command))
        finally:
            _killed(process)
    if code != 0:
        raise FailedError(f"tofu {command} exited with {code}")
    return output


class Session:
    """Args:
    env: the task environment.
    config: the result of :func:`configuration`.
    credentials: the decoded ``credentials.json``.
    workspace: the ``workspace.json`` document.
    task: the task directory holding the staged root.
    key: the state key in the workspace bucket.
    """

    def __init__(self, env, config, credentials, workspace, task, key):
        self.workspace = workspace["workspace"]
        self.zone = workspace["dns"]["zone"]
        self.bucket_name = f"{self.workspace}-state"
        self.key = key
        self.task = task
        self.config = config
        self.bao = remote.OpenBao(config["openbao"], config["cafile"])
        token = self.bao.login(
            f"{self.workspace}-provision", inputs.required(env, "SEMAPHORE_JWT")
        )
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
        dns = credentials["dns"][config["flavor"]]
        self.dns = provider_env.mapped(
            self.bao,
            dns["path"].format(workspace=self.workspace, zone=self.zone),
            dns["env"],
        )
        cleared = credential_names(credentials)
        self.environment = {
            name: value
            for name, value in env.items()
            if not name.startswith(CLEARED_PREFIXES)
            and name not in cleared
            and name not in CLEARED_NAMES
        } | {
            "TF_IN_AUTOMATION": "1",
            "TF_INPUT": "0",
            "TF_CLI_CONFIG_FILE": str(OPENTOFU / "tofurc"),
            "TF_ENCRYPTION": encryption(self.workspace),
            "BAO_ADDR": config["openbao"],
            "BAO_TOKEN": token,
            **self.dns,
        }
        if config["cafile"]:
            self.environment["BAO_CACERT"] = config["cafile"]

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
            return [(self.dns["DNS_UPDATE_SERVER"], self.dns["DNS_UPDATE_PORT"])]
        return remote.zone_servers(self.zone, RESOLV_CONF)

    def refuse_taken(self, label):
        fqdn = f"{label}.{self.workspace}.{self.zone}"
        if remote.taken(fqdn, self.servers()):
            raise inputs.RefusedError(
                f"{fqdn} already holds an A, AAAA or CNAME record"
            )

    def apply(self, label, record=None):
        """Args:
            label: the DNS label the apply creates.
            record: ``(key, document)`` written to the state bucket right
                before the apply, None for none.

        Returns:
            ``{output name: value}`` of the root.
        """
        require_snapshot(self.bao, self.workspace)
        if self.empty():
            self.refuse_taken(label)
        if record is not None:
            key, document = record
            self.bucket.put(self.bucket_name, key, json.dumps(document).encode())
        self.run("apply", "-auto-approve", "-input=false", f"-var-file={VALUES_FILE}")
        outputs = json.loads(self.run("output", "-json", capture=True))
        return {name: output["value"] for name, output in outputs.items()}

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


def live_provider(config, interface, values):
    catalogs = inputs.load_catalogs(config["catalogs"], interface)
    provider = inputs.select_provider(catalogs, values)
    return provider, catalogs[provider]


def destroy_provider(session, key, config, interface, values):
    document = session.bucket.get(session.bucket_name, key)
    if document is not None:
        return inputs.recorded_provider(document, values, interface)
    provider, catalog = live_provider(config, interface, values)
    print(f"{key} is missing, so the destroy takes {provider} from the live catalogs")
    return provider, catalog


def provision_provider(session, key, selected, line):
    document = session.bucket.get(session.bucket_name, key)
    if document is not None:
        recorded = inputs.provision_record(document)["provider"]
        if recorded != selected[0]:
            raise inputs.RefusedError(
                f"line {line} was provisioned with {recorded}, but the live "
                f"catalogs now pick {selected[0]}; applying the {selected[0]} root "
                f"to its state would destroy the {recorded} server"
            )
    return selected


def order(template, env, checkout, interface, credentials, config):
    sales_order, line = inputs.order_line(env, interface)
    workspace = inputs.workspace_document(env, interface, config["flavor"])
    name = workspace["workspace"]
    key = f"{sales_order}/{line}.tfstate"
    if template == "unlock":
        with workspace_lock(name, True), task_directory() as task:
            stage(task, OPENTOFU / "records", config["flavor"], workspace)
            session = Session(env, config, credentials, workspace, task, key)
            session.init()
            session.unlock()
        return
    source = inputs.provider_token(env, interface)
    refused = inputs.refused_files(checkout)
    if refused:
        raise inputs.RefusedError(
            f"the checkout holds infrastructure code: {', '.join(refused)}"
        )
    values = inputs.load_tfvars(checkout, f"{sales_order}-{line}", interface)
    selected = None
    if template == "provision":
        selected = live_provider(config, interface, values)
    record_key = RECORD.format(sales_order=sales_order, line=line)
    with workspace_lock(name, False), task_directory() as task:
        session = Session(env, config, credentials, workspace, task, key)
        if selected is None and session.holds_nothing(record_key):
            print(json.dumps(session.forget()))
            return
        if selected is None:
            provider, catalog = destroy_provider(
                session, record_key, config, interface, values
            )
        else:
            provider, catalog = provision_provider(
                session, record_key, selected, values["name"]
            )
        stage(task, OPENTOFU / "roots" / provider, config["flavor"], workspace)
        (task / "catalog.json").write_text(json.dumps(catalog), encoding="utf-8")
        (task / VALUES_FILE).write_text(json.dumps(values), encoding="utf-8")
        region = catalog[values["flavor"]]["regions"][values["region"]]
        session.add_provider(
            provider, credentials["providers"][provider], region, source
        )
        session.init()
        if template == "provision":
            document = {"provider": provider, "catalog": catalog}
            outputs = session.apply(values["dns_label"], (record_key, document))
        else:
            outputs = session.destroy(record_key)
        print(json.dumps(outputs))


def record(env, interface, credentials, config):
    request = inputs.dns_request(env, interface)
    workspace = inputs.workspace_document(env, interface, config["flavor"])
    key = f"{request['sales_order']}/{request['line']}.dns.tfstate"
    with task_directory() as task:
        stage(task, OPENTOFU / "records", config["flavor"], workspace)
        values = {key: request[key] for key in ("dns_label", "host", "cname")}
        (task / VALUES_FILE).write_text(json.dumps(values), encoding="utf-8")
        session = Session(env, config, credentials, workspace, task, key)
        session.init()
        if request["action"] == "create":
            print(json.dumps(session.apply(request["dns_label"])))
        elif request["action"] == "unlock":
            session.unlock()
        elif session.empty():
            print(json.dumps(session.forget()))
        else:
            print(json.dumps(session.destroy()))


def _terminate(signum, _frame):
    raise SystemExit(128 + signum)


def _over_budget(_signum, _frame):
    raise BudgetError(
        f"the run exceeded its time budget of {provider_env.RUN_BUDGET}, the "
        f"budget a customer credential must outlive"
    )


def dispatch(template, extra, env, checkout):
    if template not in TEMPLATES:
        raise inputs.RefusedError(f"names no template of {', '.join(TEMPLATES)}")
    if extra:
        raise inputs.RefusedError(f"unexpected argument {extra[0]!r}")
    interface = json.loads((OPENTOFU / "interface.json").read_text("utf-8"))
    credentials = json.loads((OPENTOFU / "credentials.json").read_text("utf-8"))
    config = configuration(env)
    if template == "dns":
        record(env, interface, credentials, config)
    else:
        order(template, env, checkout, interface, credentials, config)


def main(argv, env, checkout):
    """Args:
        argv: ``[script, template, *extra]``; the wrapper names the template.
        env: the task environment.
        checkout: the workspace checkout Semaphore runs the template in.

    Returns:
        The exit code: 0 done, 1 failed, also once the run outlives
        :data:`provider_env.RUN_BUDGET`, 2 refused.
    """
    template = argv[1] if len(argv) > 1 else ""
    prefix = f"{template or 'provision'}.sh"
    previous = signal.signal(signal.SIGALRM, _over_budget)
    signal.alarm(int(provider_env.RUN_BUDGET.total_seconds()))
    try:
        dispatch(template, argv[2:], env, checkout)
    except inputs.RefusedError as refusal:
        print(f"{prefix}: refused: {refusal}", file=sys.stderr)
        return 2
    except (FailedError, remote.RemoteError) as failure:
        print(f"{prefix}: failed: {failure}", file=sys.stderr)
        return 1
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)
    return 0


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _terminate)
    sys.exit(main(sys.argv, dict(os.environ), Path.cwd()))
