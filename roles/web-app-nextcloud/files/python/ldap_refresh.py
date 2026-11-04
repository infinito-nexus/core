"""Refresh the LDAP attributes and the address of every Nextcloud account the directory holds.

Environment:
    RBAC_SYNC_CONTAINER_BIN, RBAC_SYNC_CID: how to reach the Nextcloud container.
    RBAC_SYNC_LDAP: JSON directory settings the runner exports.
    NEXTCLOUD_USER: user ``occ`` runs as inside the container.
    NEXTCLOUD_OCC: path of ``occ`` inside the container.
    NEXTCLOUD_ADDRESS_ATTRIBUTES: JSON list of the street, postal code, locality, region
        and country attributes the address is composed of, in that order.
    RBAC_USERS: JSON list of every directory account.

Output:
    One ``CHANGED <username> address`` line per rewritten address, then
    ``REFRESHED <count>`` with the number of refreshed accounts.
"""

import json
import os
import subprocess

from ldap_client import SCOPE_ONE_LEVEL, Connection, present


def occ(environ, run, *args):
    """Return the standard output of one ``occ`` call inside the container.

    Args:
        environ: the process environment.
        run: ``subprocess.run`` or a stand-in.
        args: the ``occ`` arguments.
    """
    argv = [
        environ["RBAC_SYNC_CONTAINER_BIN"],
        "exec",
        "-i",
        "--user",
        environ["NEXTCLOUD_USER"],
        environ["RBAC_SYNC_CID"],
        "php",
        environ["NEXTCLOUD_OCC"],
        *args,
    ]
    return run(argv, capture_output=True, text=True, check=True).stdout


def compose_address(street, postal_code, locality, region, country):
    """Return the one-line postal address of the given parts, empty parts left out.

    Args:
        street: street and number.
        postal_code: postal code.
        locality: city.
        region: state or region.
        country: country code.
    """
    place = " ".join(part for part in (postal_code, locality) if part)
    return ", ".join(part for part in (street, place, region, country) if part)


def directory_addresses(environ, connect):
    """Return ``{username: address}`` of every account of the users OU.

    Args:
        environ: the process environment.
        connect: ``ldap_client.Connection`` or a stand-in.
    """
    ldap = json.loads(environ["RBAC_SYNC_LDAP"])
    login = ldap["attributes"]["id"]
    parts = json.loads(environ["NEXTCLOUD_ADDRESS_ATTRIBUTES"])
    connection = connect(ldap["uri"])
    try:
        entries = connection.search(
            ldap["users_dn"], SCOPE_ONE_LEVEL, present(login), [login, *parts]
        )
    finally:
        connection.close()
    addresses = {}
    for _, values in entries:
        logins = values.get(login.lower())
        if logins:
            addresses[logins[0]] = compose_address(
                *((values.get(part.lower()) or [""])[0] for part in parts)
            )
    return addresses


def main(environ, run=subprocess.run, connect=Connection):
    """Refresh the known directory accounts, align their addresses, print the result.

    Args:
        environ: the process environment.
        run: ``subprocess.run`` or a stand-in.
        connect: ``ldap_client.Connection`` or a stand-in.
    """
    known = set(
        json.loads(occ(environ, run, "user:list", "--output=json", "--limit=0"))
    )
    usernames = sorted(
        {account["username"] for account in json.loads(environ["RBAC_USERS"])} & known
    )
    addresses = directory_addresses(environ, connect)
    for username in usernames:
        occ(environ, run, "ldap:check-user", "--update", username)
        if username not in addresses:
            continue
        current = occ(
            environ, run, "user:profile", username, "address", "--default-value="
        ).strip()
        if current != addresses[username]:
            occ(environ, run, "user:profile", username, "address", addresses[username])
            print(f"CHANGED {username} address")
    print(f"REFRESHED {len(usernames)}")


if __name__ == "__main__":
    main(os.environ)
