"""Args:
validate: checks the survey (WORKSPACE, the bare lowercase workspace id;
    MONITOR_ACTION, ``apply`` or ``remove``; MONITOR_HOST, one inventory host
    name; for ``apply`` INVENTORY_COMMIT and DNS_LABEL, the host's deploy
    label; ``remove`` refuses both) and every setting below; a refusal prints
    the refusal line and exits 2 before any write.
inventory-key <key file> <zone file>: writes the read key of the workspace's
    inventory repository from ``platform/data/monitoring/inventory/ws-<id>``
    to the key file with mode 0600, and the DNS zone ``workspace apply`` wrote
    beside it to the zone file, for ``deploy_domain`` of ``lib.sh``.
plan <inventory file> <plan file> <primary domain>: reads ``ansible-inventory
    --list`` of the task's pinned inventory commit and writes MONITOR_HOST's
    share, address, domains, federation domain and SSH access, with the
    ``deploy_domain`` of ``lib.sh`` as DOMAIN_PRIMARY in place of the
    inventory's; ``remove`` plans no entry and takes an empty domain. Every
    name is resolved and each answer checked like a literal. A value that
    fails its check prints the refusal line and exits 2.
preflight <plan file> <login file>: refuses a DNS_LABEL bound to another host
    and any pending Checkmk change, before any write, and writes the Checkmk
    login, mode 0600.
secrets <plan file> <secrets file>: converges MONITOR_HOST's federation token
    and the digest the instance reads, mirrors the platform monitoring public
    key for an agent host, binds DNS_LABEL to MONITOR_HOST on ``apply``, and
    writes the Checkmk login and the host's token, mode 0600.
checkmk <plan file> <login file> <result file>: converges MONITOR_HOST in
    the workspace's folder, never another host, runs its service discovery
    when it shares ``agent``, and activates changes only when there are any.
prometheus <plan file> <secrets file> <state file>: writes the scrape
    configuration of MONITOR_HOST, mode 0600, for prometheus_instances.py.
settle <plan file>: exits 3 when a release claimed or released MONITOR_HOST
    while the ``apply`` ran, after every one of its writes, so
    ``monitoring.sh`` removes the Checkmk host and the scrape file again;
    0 otherwise.
result <plan file> <checkmk result> <prometheus result>: prints the last line
    ``{"workspace": <id>, "host": <host>, "checkmk": .., "prometheus": ..}``.

Settings, each required and checked by every command: ``SETTINGS`` of
``monitoring/survey.py``. The ``validate`` command also requires its
``SHELL_SETTINGS`` and ``PRESENT_SETTINGS``, everything ``monitoring.sh``
reads, so a missing one refuses before any write.
``secrets``, ``preflight``, ``settle`` and ``inventory-key`` read BAO_ADDR, BAO_CACERT, BAO_TOKEN_FILE
and INFINITO_SRC_DIR. No credential reaches an argument or the output.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from monitoring.checkmk import Checkmk
from monitoring.openbao import (
    CHECKMK_PATH,
    MOUNT,
    converge_secrets,
    inventory_key,
    label_refusal,
    mint_token,
    openbao,
    released,
    released_refusal,
    workspace_digest_file,
)
from monitoring.plan import plan, resolve
from monitoring.prometheus import prometheus_state
from monitoring.rest import rest_api
from monitoring.survey import (
    SCRIPT,
    RefusalError,
    RunError,
    refusal_line,
    settings,
    shell_settings,
    validate,
)

SECRET_MODE = 0o600
SETTLE_RELEASED = 3
UNDO_VAR = "MONITOR_UNDO"


def result_line(planned, checkmk, prometheus):
    """Args:
    planned: the result of ``plan``.
    checkmk: ``hosts`` of the checkmk result, whether MONITOR_HOST is in Checkmk.
    prometheus: the output of ``prometheus_instances.py``, whose ``kept``
        tells whether MONITOR_HOST's scrape file stays.

    Returns:
        The last line of a successful run.
    """
    return json.dumps(
        {
            "workspace": planned["workspace"],
            "host": planned["host"],
            "checkmk": bool(checkmk),
            "prometheus": bool(prometheus.get("kept")),
        }
    )


def write_private(path, text):
    target = Path(path)
    target.touch(mode=SECRET_MODE)
    target.chmod(SECRET_MODE)
    target.write_text(text, encoding="utf-8")


def write_secret(path, value):
    write_private(path, json.dumps(value))


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def remote_outcome(path):
    """Args:
    path: the result ``ansible -t`` wrote for the Prometheus host.

    Returns:
        The JSON line ``prometheus_instances.py`` printed last.
    """
    lines = (load(path).get("stdout") or "").strip().splitlines()
    if not lines:
        raise RunError("the Prometheus host printed no outcome")
    return json.loads(lines[-1])


def site_of(login, config, sleep, api):
    """Args:
    login: the Checkmk automation login, ``username`` and ``secret``.
    config: the result of ``settings``.
    sleep: ``time.sleep`` or a stand-in.
    api: a stand-in for the Checkmk call function, None for ``rest_api``.

    Returns:
        The ``Checkmk`` of the platform's site, signed in as ``login``.
    """
    return Checkmk(
        api
        or rest_api(
            config["api"], login["username"], login["secret"], config["cacert"]
        ),
        config["site"],
        sleep,
        login["username"],
    )


def openbao_step(command, args, workspace, config, client, sleep, api):
    """Args:
    command: ``inventory-key``, ``preflight`` or ``secrets``.
    args: its arguments.
    workspace: the bare workspace id.
    config: the result of ``settings``.
    client: an ``OpenBaoClient`` logged in as the ``monitoring`` role.
    sleep: ``time.sleep`` or a stand-in.
    api: a stand-in for the Checkmk call function, else None.
    """
    if command == "inventory-key":
        key, zone = inventory_key(client, workspace)
        write_private(args[0], key.rstrip("\n") + "\n")
        Path(args[1]).write_text(f"{zone}\n", encoding="utf-8")
    elif command == "preflight":
        planned = load(args[0])
        released_refusal(client, planned)
        if planned["action"] == "apply":
            workspace_digest_file(client, planned["alias"])
        label_refusal(client, planned)
        login = {"checkmk": client.read_all(MOUNT, CHECKMK_PATH)}
        site_of(login["checkmk"], config, sleep, api).refuse_pending_changes()
        write_secret(args[1], login)
    else:
        write_secret(args[1], converge_secrets(client, load(args[0]), mint_token))


# Real I/O by default: __main__ passes none, tests pass stand-ins.
def main(
    argv,
    env,
    stdout=sys.stdout,
    sleep=time.sleep,
    api=None,
    bao=None,
    resolver=resolve,
):
    """Args:
    argv: the command line after the script name.
    env: the task environment.
    stdout: where the refusal and result lines go.
    sleep: ``time.sleep`` or a stand-in.
    api: a stand-in for the Checkmk call function, else ``rest_api``.
    bao: a stand-in ``(error, client)`` for ``openbao``.
    resolver: ``resolve`` or a stand-in.

    Returns:
        The exit code: 2 for a refusal, 1 for a failure.
    """
    commands = {
        "refuse": 1,
        "validate": 0,
        "inventory-key": 2,
        "plan": 3,
        "preflight": 2,
        "secrets": 2,
        "settle": 1,
        "checkmk": 3,
        "prometheus": 3,
        "result": 3,
    }
    if not argv or argv[0] not in commands or len(argv) != commands[argv[0]] + 1:
        print(f"{SCRIPT}: expects one of {', '.join(commands)}", file=sys.stderr)
        return 2
    command, args = argv[0], argv[1:]
    if command == "refuse":
        print(refusal_line(env.get("WORKSPACE") or None, args[0]), file=stdout)
        return 2
    try:
        workspace, action, host = validate(env)
        config = settings(env)
        if command == "validate":
            shell_settings(env)
        elif command == "plan":
            write_secret(
                args[1],
                plan(
                    workspace,
                    action,
                    host,
                    load(args[0]),
                    config["private"],
                    args[2],
                    resolver,
                ),
            )
        elif command in ("inventory-key", "secrets", "preflight", "settle"):
            failure, client = bao or openbao(env)
            try:
                if command == "settle":
                    return SETTLE_RELEASED if released(client, load(args[0])) else 0
                openbao_step(command, args, workspace, config, client, sleep, api)
            except failure as error:
                raise RunError(str(error)) from error
        elif command == "checkmk":
            planned = load(args[0])
            site = site_of(load(args[1])["checkmk"], config, sleep, api)
            held = (
                site.apply(planned, config["tls_days"])
                if planned["action"] == "apply"
                else site.remove(
                    planned["alias"], planned["host"], env.get(UNDO_VAR) == "1"
                )
            )
            write_secret(args[2], {"hosts": held, "changed": site.changed})
        elif command == "prometheus":
            write_secret(
                args[2],
                prometheus_state(load(args[0]), load(args[1])["token"]),
            )
        elif command == "result":
            print(
                result_line(
                    load(args[0]), load(args[1])["hosts"], remote_outcome(args[2])
                ),
                file=stdout,
            )
    except RefusalError as error:
        print(refusal_line(env.get("WORKSPACE") or None, str(error)), file=stdout)
        return 2
    except RunError as error:
        print(f"{SCRIPT}: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:], os.environ.copy()))
