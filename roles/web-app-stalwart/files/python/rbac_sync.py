"""Converge Stalwart's System Administrator role on the administrator role group.

Environment:
    RBAC_SYNC_CONTAINER_BIN, RBAC_SYNC_CID: how to reach the Stalwart container.
    STALWART_CURL: the curl base command of a JMAP call.
    STALWART_JMAP_URL: the JMAP endpoint inside the container.
    STALWART_JMAP_TRANSIENT_ERRORS: JSON list of the JMAP error types a call retries.
    STALWART_ADMIN_USER, STALWART_ADMIN_PASSWORD: the recovery administrator;
        they reach curl on standard input only.
    STALWART_DOMAIN: the mail domain whose user accounts are reconciled.
    STALWART_RBAC_KEEP: JSON list of account names that hold System Administrator outside the role.
    RBAC_ADMINISTRATORS: JSON list of the administrator role's usernames.

Output:
    One ``CHANGED <account> <role>`` line per changed account, else ``UNCHANGED``.
"""

import json
import os
import shlex
import subprocess
import time

from stalwart_admin_plan import stalwart_admin_plan

USING = ["urn:ietf:params:jmap:core", "urn:stalwart:jmap"]
ATTEMPTS = 12
DELAY_SECONDS = 5
ADMIN_ROLE = "System Administrator"
USER_ROLE = "User"


def jmap(environ, run, sleep, method, arguments):
    """Return the arguments of the response to one management JMAP method call.

    Args:
        environ: the process environment.
        run: ``subprocess.run`` or a stand-in.
        sleep: ``time.sleep`` or a stand-in.
        method: the JMAP method name.
        arguments: the method arguments.
    """
    argv = [
        environ["RBAC_SYNC_CONTAINER_BIN"],
        "exec",
        "-i",
        environ["RBAC_SYNC_CID"],
        *shlex.split(environ["STALWART_CURL"]),
        "-sS",
        "-f",
        "-K",
        "-",
        "-H",
        "Content-Type:application/json",
        environ["STALWART_JMAP_URL"],
    ]
    credentials = (
        f"{environ['STALWART_ADMIN_USER']}:{environ['STALWART_ADMIN_PASSWORD']}"
    )
    body = json.dumps({"using": USING, "methodCalls": [[method, arguments, "c0"]]})
    config = (
        f"user = {json.dumps(credentials, ensure_ascii=False)}\n"
        f"data-binary = {json.dumps(body, ensure_ascii=False)}\n"
    )
    transient = json.loads(environ["STALWART_JMAP_TRANSIENT_ERRORS"])
    for attempt in range(1, ATTEMPTS + 1):
        result = run(argv, input=config, capture_output=True, text=True, check=False)
        if result.returncode == 0:
            name, response = json.loads(result.stdout)["methodResponses"][0][:2]
            if name != "error":
                return response
            if response["type"] not in transient:
                raise SystemExit(f"Stalwart refused {method}: {json.dumps(response)}")
            failure = f"Stalwart kept answering {method} with {response['type']}"
        else:
            failure = (
                f"curl exited {result.returncode} on {method}: {result.stderr.strip()}"
            )
        if attempt < ATTEMPTS:
            sleep(DELAY_SECONDS)
    raise SystemExit(failure)


def role_ids(account):
    """Return the role ids an account holds.

    Args:
        account: one ``x:Account/get`` entry.
    """
    return (account.get("roles") or {}).get("roleIds") or {}


def first_id(entries, key, value):
    """Return the id of the first entry whose ``key`` equals ``value``.

    Args:
        entries: a ``/get`` list.
        key: the field to match.
        value: the wanted value.
    """
    for entry in entries:
        if entry.get(key) == value:
            return entry["id"]
    raise SystemExit(f"Stalwart holds no entry with {key} {value!r}")


def main(environ, run=subprocess.run, sleep=time.sleep):
    """Grant System Administrator to the members, strip it from the rest, print the result.

    Args:
        environ: the process environment.
        run: ``subprocess.run`` or a stand-in.
        sleep: ``time.sleep`` or a stand-in.
    """
    domain = environ["STALWART_DOMAIN"]
    domain_id = first_id(
        jmap(environ, run, sleep, "x:Domain/get", {"ids": None})["list"], "name", domain
    )
    roles = jmap(environ, run, sleep, "x:Role/get", {"ids": None})["list"]
    admin_role = first_id(roles, "description", ADMIN_ROLE)
    user_role = first_id(roles, "description", USER_ROLE)
    names = list(
        dict.fromkeys(
            json.loads(environ["STALWART_RBAC_KEEP"])
            + json.loads(environ["RBAC_ADMINISTRATORS"])
        )
    )
    accounts = {
        account["id"]: account
        for account in jmap(environ, run, sleep, "x:Account/get", {"ids": None})["list"]
    }
    plan = stalwart_admin_plan(list(accounts.values()), domain_id, names, admin_role)
    if not plan["grant_ids"]:
        raise SystemExit(
            f"Stalwart holds no account on {domain} for {', '.join(names)}, "
            "so nobody would administer the mail server through SSO."
        )

    admin_ids = {admin_role: True, user_role: True}
    demoted_ids = {user_role: True}
    grants = [
        account_id
        for account_id in plan["grant_ids"]
        if role_ids(accounts[account_id]) != admin_ids
    ]
    revokes = plan["revoke_ids"]
    if not grants and not revokes:
        print("UNCHANGED")
        return

    update = {
        account_id: {"roles": {"@type": "Custom", "roleIds": admin_ids}}
        for account_id in grants
    }
    update.update(
        {
            account_id: {"roles": {"@type": "Custom", "roleIds": demoted_ids}}
            for account_id in revokes
        }
    )
    response = jmap(environ, run, sleep, "x:Account/set", {"update": update})
    if response.get("notUpdated"):
        raise SystemExit(
            f"Stalwart refused the role change: {json.dumps(response['notUpdated'])}"
        )

    read = {
        account["id"]: account
        for account in jmap(
            environ, run, sleep, "x:Account/get", {"ids": grants + revokes}
        )["list"]
    }
    ungranted = [
        accounts[account_id]["name"]
        for account_id in grants
        if account_id not in read or role_ids(read[account_id]) != admin_ids
    ]
    unrevoked = [
        accounts[account_id]["name"]
        for account_id in revokes
        if account_id in read and admin_role in role_ids(read[account_id])
    ]
    if ungranted or unrevoked:
        raise SystemExit(
            "Stalwart accepted the role change but read back "
            f"{', '.join(ungranted) or 'none'} without System Administrator and "
            f"{', '.join(unrevoked) or 'none'} still holding it."
        )
    for account_id in grants:
        print(f"CHANGED {accounts[account_id]['name']} system-administrator")
    for account_id in revokes:
        print(f"CHANGED {accounts[account_id]['name']} user")


if __name__ == "__main__":
    main(os.environ)
