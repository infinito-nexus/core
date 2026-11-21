from __future__ import annotations

import contextlib
import ctypes
import fcntl
import functools
import json
import os
import shutil
import signal
import sys
import tempfile
from pathlib import Path

from provision import inputs, opentofu, provider_env, remote, sandbox, zone
from provision.session import OPENTOFU, VALUES_FILE, opened

TEMPLATES = ("provision", "destroy", "unlock", "dns", "zone")
ORDER_TEMPLATES = ("provision", "destroy")
PROVISION_ROLE = "provision"
ZONE_ROLE = "zone"
ZONE_STATE = "{sales_order}/{line}.zone.tfstate"
ZONE_LOCK = "{workspace}.{sales_order}-{line}.zone"
LOCKS_MODE = 0o700
TASK_JWT = "SEMAPHORE_JWT"
TASK_JWT_FD = 3
PR_GET_DUMPABLE = 3
PR_SET_DUMPABLE = 4
RECORD = "{sales_order}/{line}.provision.json"
FAILURES = (opentofu.FailedError, remote.RemoteError, sandbox.SandboxError)


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


@contextlib.contextmanager
def task_directory():
    """Returns:
    The task directory of the run's own OpenTofu sandbox, whose processes,
    files and uid the spawner takes back once the block ends.
    """
    stack = contextlib.ExitStack()
    with remote.alarm_deferred():
        path = stack.enter_context(sandbox.opened())
    try:
        yield path
    finally:
        with remote.alarm_deferred():
            stack.close()


@contextlib.contextmanager
def task_lock(name, mode, refusal):
    """Args:
    name: the lock file name below ``sandbox.LOCKS``, without ``.lock``.
    mode: the ``fcntl.flock`` operation.
    refusal: the refusal when ``mode`` is non-blocking and the lock is held.
    """
    directory = Path(tempfile.gettempdir()) / sandbox.LOCKS
    directory.mkdir(mode=LOCKS_MODE, exist_ok=True)
    with (directory / f"{name}.lock").open("a", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle, mode)
        except BlockingIOError:
            raise inputs.RefusedError(refusal) from None
        yield


def workspace_lock(workspace, exclusive):
    mode = (fcntl.LOCK_EX | fcntl.LOCK_NB) if exclusive else fcntl.LOCK_SH
    refusal = f"a provision or destroy task of {workspace} is running"
    return task_lock(workspace, mode, refusal)


def line_lock(workspace, sales_order, line):
    refusal = f"a zone task of {sales_order}-{line} in {workspace} is running"
    return task_lock(
        ZONE_LOCK.format(workspace=workspace, sales_order=sales_order, line=line),
        fcntl.LOCK_EX | fcntl.LOCK_NB,
        refusal,
    )


def staged(source, task, *ignored):
    """Args:
    source: the directory whose entries go into ``task``.
    task: the task directory of a sandbox; its own mode and group stay the
        spawner's, as a copy of the mode of ``source`` would drop the group
        bits the sandbox reaches its files through.
    ignored: the patterns of the entries left out at every level.
    """
    ignore = shutil.ignore_patterns(*ignored)
    names = sorted(os.listdir(source))
    skipped = ignore(str(source), names)
    for name in names:
        if name in skipped:
            continue
        entry = Path(source) / name
        if entry.is_dir():
            shutil.copytree(entry, task / name, ignore=ignore, dirs_exist_ok=True)
        else:
            shutil.copy2(entry, task / name)


def stage(task, root, flavor, workspace):
    staged(root, task, "catalog.json", "workspace.json", ".terraform")
    shutil.copytree(OPENTOFU / "modules" / f"dns-{flavor}", task / "modules" / "dns")
    sandbox.task_write(task, "workspace.json", json.dumps(workspace))


def provider_role(provider):
    """Args:
        provider: the provider the template pins.

    Returns:
        The suffix of the workspace's task token role that binds the template
        and whose policy reads that provider's secrets and no other provider's.
    """
    return f"{PROVISION_ROLE}-{provider}"


def pinned_provider(template, arguments, providers):
    """Args:
        template: the template the wrapper names.
        arguments: the arguments after it.
        providers: the providers of ``credentials.json``.

    Returns:
        ``(provider, rest)``: the provider a provision or destroy template
        pins as its locked first argument, None for any other template, and
        the arguments after it.
    """
    if template not in ORDER_TEMPLATES:
        return None, arguments
    if not arguments or arguments[0] not in providers:
        raise inputs.RefusedError(
            f"the {template} template pins no provider of {', '.join(providers)}"
        )
    return arguments[0], arguments[1:]


def require_pinned(pinned, provider, line):
    if provider != pinned:
        raise inputs.RefusedError(
            f"line {line} is on {provider}, but this template pins {pinned}; "
            f"run the {provider} template of the workspace"
        )


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


def order(template, pinned, env, checkout, interface, credentials, config):
    sales_order, line = inputs.order_line(env, interface)
    workspace = inputs.workspace_document(env, interface, config["flavor"])
    name = workspace["workspace"]
    key = f"{sales_order}/{line}.tfstate"
    reach = credentials["dns"][config["flavor"]]
    if template == "unlock":
        with workspace_lock(name, True), task_directory() as task:
            stage(task, OPENTOFU / "records", config["flavor"], workspace)
            with opened(
                env, config, credentials, workspace, task, key, PROVISION_ROLE
            ) as session:
                session.open(reach)
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
        require_pinned(pinned, selected[0], values["name"])
    record_key = RECORD.format(sales_order=sales_order, line=line)
    with (
        workspace_lock(name, False),
        task_directory() as task,
        opened(
            env, config, credentials, workspace, task, key, provider_role(pinned)
        ) as session,
    ):
        if selected is None and session.holds_nothing(record_key):
            print(json.dumps(session.forget()))
            return
        if selected is None:
            provider, catalog = destroy_provider(
                session, record_key, config, interface, values
            )
            require_pinned(pinned, provider, values["name"])
        else:
            provider, catalog = provision_provider(
                session, record_key, selected, values["name"]
            )
        session.open(reach)
        stage(task, OPENTOFU / "roots" / provider, config["flavor"], workspace)
        sandbox.task_write(task, "catalog.json", json.dumps(catalog))
        sandbox.task_write(task, VALUES_FILE, json.dumps(values))
        region = catalog[values["flavor"]]["regions"][values["region"]]
        session.add_provider(
            provider, credentials["providers"][provider], region, source
        )
        session.init()
        if template == "provision":
            document = {"provider": provider, "catalog": catalog}
            unclaimed = functools.partial(session.refuse_taken, values["dns_label"])
            outputs = session.apply(unclaimed, (record_key, document))
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
        sandbox.task_write(task, VALUES_FILE, json.dumps(values))
        reach = credentials["dns"][config["flavor"]]
        with opened(
            env, config, credentials, workspace, task, key, PROVISION_ROLE
        ) as session:
            session.open(reach)
            session.init()
            if request["action"] == "create":
                unclaimed = functools.partial(
                    session.refuse_taken, request["dns_label"]
                )
                print(json.dumps(session.apply(unclaimed)))
            elif request["action"] == "unlock":
                session.unlock()
            elif session.empty():
                print(json.dumps(session.forget()))
            else:
                print(json.dumps(session.destroy()))


def zone_lifecycle(env, interface, credentials, config):
    sales_order, line = inputs.order_line(env, interface)
    handler = zone.ZONE_HANDLERS[inputs.required(env, "ZONE_ACTION")]
    domain = env.get("DOMAIN", "")
    workspace = inputs.workspace_document(env, interface, config["flavor"])
    key = ZONE_STATE.format(sales_order=sales_order, line=line)
    reach = credentials["zone"]
    exclusive = handler is zone.zone_unlock
    with (
        workspace_lock(workspace["workspace"], exclusive),
        line_lock(workspace["workspace"], sales_order, line),
        task_directory() as task,
    ):
        staged(OPENTOFU / "zone", task, ".terraform")
        values = sandbox.task_write(task, VALUES_FILE, json.dumps({"domain": domain}))
        with opened(
            env, config, credentials, workspace, task, key, ZONE_ROLE
        ) as session:
            session.open(reach)
            session.init()
            handler(session, reach, values, domain)


def _terminate(signum, _frame):
    raise SystemExit(128 + signum)


def _over_budget(_signum, _frame):
    raise opentofu.BudgetError(
        f"the run exceeded its time budget of {provider_env.RUN_BUDGET}, the "
        f"budget a customer credential must outlive"
    )


def dispatch(template, extra, env, checkout):
    if template not in TEMPLATES:
        raise inputs.RefusedError(f"names no template of {', '.join(TEMPLATES)}")
    interface = json.loads((OPENTOFU / "interface.json").read_text("utf-8"))
    credentials = json.loads((OPENTOFU / "credentials.json").read_text("utf-8"))
    pinned, extra = pinned_provider(template, extra, credentials["providers"])
    if extra:
        raise inputs.RefusedError(f"unexpected argument {extra[0]!r}")
    config = configuration(env)
    if template == "dns":
        record(env, interface, credentials, config)
    elif template == "zone":
        zone_lifecycle(env, interface, credentials, config)
    else:
        order(template, pinned, env, checkout, interface, credentials, config)


def main(argv, env, checkout):
    """Args:
        argv: ``[script, template, *extra]``; the wrapper names the template,
            and a provision or destroy template pins its provider as the
            first of ``extra``.
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
    except FAILURES as failure:
        print(f"{prefix}: failed: {failure}", file=sys.stderr)
        return 1
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)
    return 0


def task_token(descriptor):
    """Args:
        descriptor: the file descriptor the wrapper hands the task token on.

    Returns:
        The task token, read once; the descriptor is closed after it.
    """
    with os.fdopen(descriptor, encoding="utf-8") as handle:
        return handle.read().strip()


def undumpable():
    """Returns:
        Once the process is no longer dumpable, so a process of the same uid,
        an OpenTofu plugin among them, reads neither its memory nor its
        environment through ``/proc``; ``execve`` gives OpenTofu its own flag.

    Raises:
        OSError: the kernel refused or kept the process dumpable.
    """
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(PR_SET_DUMPABLE, 0, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "prctl(PR_SET_DUMPABLE, 0) failed")
    if libc.prctl(PR_GET_DUMPABLE, 0, 0, 0, 0) != 0:
        raise OSError("prctl(PR_SET_DUMPABLE, 0) left the process dumpable")


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _terminate)
    undumpable()
    if TASK_JWT in os.environ:
        print(
            f"provision.py: refused: {TASK_JWT} is in the environment; the "
            f"wrapper hands it on descriptor {TASK_JWT_FD}",
            file=sys.stderr,
        )
        sys.exit(2)
    jwt = task_token(TASK_JWT_FD)
    sys.exit(main(sys.argv, {**os.environ, TASK_JWT: jwt}, Path.cwd()))
