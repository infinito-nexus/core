from __future__ import annotations

import contextlib
import fcntl
import functools
import json
import os
import shutil
import signal
import sys
import tempfile
from pathlib import Path

from provision import inputs, opentofu, provider_env, remote
from provision.session import OPENTOFU, VALUES_FILE, Session

TEMPLATES = ("provision", "destroy", "unlock", "dns", "zone")
PROVISION_ROLE = "provision"
ZONE_ROLE = "zone"
ZONE_STATE = "{sales_order}/{line}.zone.tfstate"
ZONE_LOCK = "{workspace}.{sales_order}-{line}.zone"
ZONE_OUTPUTS = ("zone", "zone_id", "status", "name_servers")
ZONE_RESOURCE = "cloudflare_zone.zone"
LOCKS = "provision-locks"
RECORD = "{sales_order}/{line}.provision.json"


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
    path = Path(tempfile.mkdtemp(prefix="provision-task-"))
    try:
        yield path
    finally:
        with remote.alarm_deferred():
            shutil.rmtree(path, ignore_errors=True)


@contextlib.contextmanager
def task_lock(name, mode, refusal):
    """Args:
    name: the lock file name below ``LOCKS``, without ``.lock``.
    mode: the ``fcntl.flock`` operation.
    refusal: the refusal when ``mode`` is non-blocking and the lock is held.
    """
    directory = Path(tempfile.gettempdir()) / LOCKS
    directory.mkdir(mode=0o700, exist_ok=True)
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


def stage(task, root, flavor, workspace):
    shutil.copytree(
        root,
        task,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("catalog.json", "workspace.json", ".terraform"),
    )
    shutil.copytree(OPENTOFU / "modules" / f"dns-{flavor}", task / "modules" / "dns")
    (task / "workspace.json").write_text(json.dumps(workspace), encoding="utf-8")


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
    reach = credentials["dns"][config["flavor"]]
    if template == "unlock":
        with workspace_lock(name, True), task_directory() as task:
            stage(task, OPENTOFU / "records", config["flavor"], workspace)
            session = Session(
                env, config, credentials, workspace, task, key, reach, PROVISION_ROLE
            )
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
        session = Session(
            env, config, credentials, workspace, task, key, reach, PROVISION_ROLE
        )
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
        (task / VALUES_FILE).write_text(json.dumps(values), encoding="utf-8")
        reach = credentials["dns"][config["flavor"]]
        session = Session(
            env, config, credentials, workspace, task, key, reach, PROVISION_ROLE
        )
        session.init()
        if request["action"] == "create":
            unclaimed = functools.partial(session.refuse_taken, request["dns_label"])
            print(json.dumps(session.apply(unclaimed)))
        elif request["action"] == "unlock":
            session.unlock()
        elif session.empty():
            print(json.dumps(session.forget()))
        else:
            print(json.dumps(session.destroy()))


def reached_field(session, reach, field):
    """Args:
        session: a :class:`Session` opened with ``reach``.
        reach: the ``{path, env}`` entry of ``credentials.json``.
        field: a field of the record at its path.

    Returns:
        The value the session read from that field.
    """
    (name,) = [name for name, source in reach["env"].items() if source == field]
    return session.reached[name]


def state_zone(session):
    """Args:
        session: a :class:`Session` of the zone root.

    Returns:
        The outputs of the zone the state holds, ``{}`` for a state without
        resources.

    Raises:
        FailedError: the state holds resources without every zone output, as
            an interrupted apply leaves it.
    """
    addresses = session.addresses()
    if not addresses:
        return {}
    held = session.outputs()
    missing = sorted(set(ZONE_OUTPUTS) - set(held))
    if missing:
        raise opentofu.FailedError(
            f"{session.key} holds {', '.join(addresses)} without the outputs "
            f"{', '.join(missing)}; an interrupted apply left it, so create and "
            f"show refuse to replace or report it until delete removes it"
        )
    return held


def held_zone(session, domain):
    """Args:
        session: a :class:`Session` of the zone root.
        domain: ``DOMAIN`` of the task.

    Returns:
        The outputs of the zone the state holds, ``{}`` for none.

    Raises:
        RefusedError: the state holds a zone of another name.
    """
    held = state_zone(session)
    if held and held["zone"] != domain:
        raise inputs.RefusedError(
            f"{session.key} holds the zone {held['zone']}, not DOMAIN {domain}; "
            f"delete it before a create of {domain}"
        )
    return held


def zone_api(session, reach):
    return remote.Cloudflare(reach["api"], reached_field(session, reach, "token"))


def zone_unlock(session, _reach, _values, _domain):
    session.unlock()


def state_domain(session):
    """Args:
        session: a :class:`Session` of the zone root whose state holds resources.

    Returns:
        The ``name`` of the zone resource the state holds, read from the state
        itself, so a state an interrupted apply left without outputs names it too.

    Raises:
        FailedError: the state names no zone resource with a name.
    """
    try:
        shown = json.loads(session.run("show", "-json", capture=True))
        resources = shown["values"]["root_module"]["resources"]
        (domain,) = [
            resource["values"]["name"]
            for resource in resources
            if resource["address"] == ZONE_RESOURCE
        ]
    except (ValueError, KeyError, TypeError):
        domain = None
    if not isinstance(domain, str) or not domain:
        raise opentofu.FailedError(
            f"{session.key} names no {ZONE_RESOURCE} with a name, so delete keeps it"
        )
    return domain


def zone_delete(session, _reach, values, _domain):
    if not session.addresses():
        session.forget()
        print(json.dumps({"deleted": True, "zone": None}))
        return
    zone = state_domain(session)
    values.write_text(json.dumps({"domain": zone}), "utf-8")
    session.destroy()
    print(json.dumps({"deleted": True, "zone": zone}))


def zone_show(session, reach, _values, domain):
    held = held_zone(session, domain)
    if not held:
        raise inputs.RefusedError(f"{session.key} holds no zone {domain}")
    live = zone_api(session, reach).zone(held["zone_id"])
    print(json.dumps({"zone": domain, "zone_id": held["zone_id"], **live}))


def zone_create(session, reach, _values, domain):
    held_zone(session, domain)
    cloudflare = zone_api(session, reach)
    account = reached_field(session, reach, "account_id")

    def unclaimed():
        if cloudflare.held(domain, account):
            raise inputs.RefusedError(
                f"the Cloudflare account already holds DOMAIN {domain} "
                f"outside {session.key}"
            )

    outputs = session.apply(unclaimed)
    print(json.dumps({name: outputs[name] for name in ZONE_OUTPUTS}))


ZONE_HANDLERS = {
    "create": zone_create,
    "show": zone_show,
    "delete": zone_delete,
    "unlock": zone_unlock,
}


def zone_lifecycle(env, interface, credentials, config):
    sales_order, line = inputs.order_line(env, interface)
    handler = ZONE_HANDLERS[inputs.required(env, "ZONE_ACTION")]
    domain = env.get("DOMAIN", "")
    workspace = inputs.workspace_document(env, interface, config["flavor"])
    key = ZONE_STATE.format(sales_order=sales_order, line=line)
    reach = credentials["zone"]
    exclusive = handler is zone_unlock
    with (
        workspace_lock(workspace["workspace"], exclusive),
        line_lock(workspace["workspace"], sales_order, line),
        task_directory() as task,
    ):
        shutil.copytree(
            OPENTOFU / "zone",
            task,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns(".terraform"),
        )
        values = task / VALUES_FILE
        values.write_text(json.dumps({"domain": domain}), "utf-8")
        session = Session(
            env, config, credentials, workspace, task, key, reach, ZONE_ROLE
        )
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
    if extra:
        raise inputs.RefusedError(f"unexpected argument {extra[0]!r}")
    interface = json.loads((OPENTOFU / "interface.json").read_text("utf-8"))
    credentials = json.loads((OPENTOFU / "credentials.json").read_text("utf-8"))
    config = configuration(env)
    if template == "dns":
        record(env, interface, credentials, config)
    elif template == "zone":
        zone_lifecycle(env, interface, credentials, config)
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
    except (opentofu.FailedError, remote.RemoteError) as failure:
        print(f"{prefix}: failed: {failure}", file=sys.stderr)
        return 1
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)
    return 0


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _terminate)
    sys.exit(main(sys.argv, dict(os.environ), Path.cwd()))
