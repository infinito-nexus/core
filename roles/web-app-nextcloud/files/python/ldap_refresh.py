"""Refresh the LDAP attributes and the address of every Nextcloud account the directory holds,
and take every ``user_oidc`` account out of the groups whose role it no longer holds.

Environment:
    RBAC_SYNC_CONTAINER_BIN, RBAC_SYNC_CID: how to reach the Nextcloud container.
    RBAC_SYNC_MEMBERS_FILE: JSON ``{"@users": [members], <role>: [members]}`` the
        runner hands over, every member with the address attributes base64-encoded
        under ``attributes``; a member without ``attributes`` is refreshed and keeps
        its address.
    NEXTCLOUD_USER: user ``occ`` runs as inside the container.
    NEXTCLOUD_OCC: path of ``occ`` inside the container, in the server root.
    NEXTCLOUD_ADDRESS_ATTRIBUTES: JSON list of the street, postal code, locality, region
        and country attributes the address is composed of, in that order.
    NEXTCLOUD_LDAP_USER_LISTING: ``true`` when ``user_ldap`` lists the directory,
        ``false`` when it maps an account only at its first login.
    NEXTCLOUD_USER_OIDC_GROUP_ROLES: JSON ``{group: role}`` of the Nextcloud groups
        ``user_oidc`` provisions from a client role, each with the role whose members
        hold that client role; ``{}`` while ``user_oidc`` is not the sign-in plugin.
    NEXTCLOUD_RBAC_KEEP: JSON list of the logins no such group loses, under the local
        account and under the directory account of the login.

Output:
    One ``CHANGED <account> left <group>`` line per account taken out of a group, one
    ``CHANGED <account> address`` line per rewritten address, then ``REFRESHED <count>``
    with the number of refreshed accounts; one ``FAILED`` line with the member and
    mapping counts and exit code 1 when directory members exist but none of them
    matches a mapped account.
"""

import base64
import json
import os
import subprocess
import sys
from pathlib import Path, PurePosixPath

USERS_ROLE = "@users"
MAPPING_PREFIX = "LDAP_MAPPING "
MAPPING_PROGRAM = "ldap_user_mapping.php"
USER_OIDC_BACKEND = "user_oidc"


def php(environ, run, *args, stdin=None):
    """Return the standard output of one ``php`` call inside the container.

    Args:
        environ: the process environment.
        run: ``subprocess.run`` or a stand-in.
        args: the ``php`` arguments.
        stdin: the script ``php`` reads from its standard input, or None.
    """
    argv = [
        environ["RBAC_SYNC_CONTAINER_BIN"],
        "exec",
        "-i",
        "--user",
        environ["NEXTCLOUD_USER"],
        environ["RBAC_SYNC_CID"],
        "php",
        *args,
    ]
    return run(argv, input=stdin, capture_output=True, text=True, check=True).stdout


def occ(environ, run, *args):
    """Return the standard output of one ``occ`` call inside the container.

    Args:
        environ: the process environment.
        run: ``subprocess.run`` or a stand-in.
        args: the ``occ`` arguments.
    """
    return php(environ, run, environ["NEXTCLOUD_OCC"], *args)


def ldap_accounts(environ, run):
    """Return ``{directory uuid: Nextcloud account}`` of every account ``user_ldap`` mapped.

    Args:
        environ: the process environment.
        run: ``subprocess.run`` or a stand-in.
    """
    root = str(PurePosixPath(environ["NEXTCLOUD_OCC"]).parent)
    program = Path(__file__).with_name(MAPPING_PROGRAM).read_text(encoding="utf-8")
    output = php(environ, run, "--", root, stdin=program)
    line = next(line for line in output.splitlines() if line.startswith(MAPPING_PREFIX))
    return json.loads(line.removeprefix(MAPPING_PREFIX))


def read_members(environ):
    """Args:
        environ: the process environment.

    Returns:
        ``{role: [members]}`` the runner hands over.
    """
    return json.loads(
        Path(environ["RBAC_SYNC_MEMBERS_FILE"]).read_text(encoding="utf-8")
    )


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


def directory_addresses(environ, members):
    """Return ``{directory uuid: address}`` of the accounts of the users OU.

    Args:
        environ: the process environment.
        members: the ``@users`` members the runner hands over.

    Returns:
        The composed address of every account by its uuid, None for an account
        that carries no address attributes.
    """
    parts = json.loads(environ["NEXTCLOUD_ADDRESS_ATTRIBUTES"])
    return {
        member["uuid"]: compose_address(
            *(
                base64.b64decode(member["attributes"][part]).decode("utf-8")
                for part in parts
            )
        )
        if "attributes" in member
        else None
        for member in members
        if member["uuid"]
    }


def unmatched_reason(members, mapped, listing):
    """Args:
        members: how many directory members carry a uuid.
        mapped: how many accounts ``user_ldap`` mapped.
        listing: whether ``user_ldap`` lists the directory.

    Returns:
        Why no member matching a mapped account is a failure, or an empty string
        when there is legitimately nothing to refresh: no members, or an empty
        mapping while ``user_ldap`` maps accounts only at their first login.
    """
    if mapped:
        return (
            f"none of the {members} directory members matches one of the "
            f"{mapped} accounts user_ldap mapped"
        )
    if members and listing:
        return (
            f"user_ldap mapped none of the {members} directory members "
            "although it lists the directory"
        )
    return ""


def account_names(members, mapped):
    """Args:
        members: directory members.
        mapped: ``{directory uuid: Nextcloud account}`` of every account ``user_ldap`` mapped.

    Returns:
        Every Nextcloud account the members sign in as: the login, which
        ``user_oidc`` takes as the user id of an account of its own, and the
        account ``user_ldap`` mapped for the member's uuid.
    """
    return {member["username"] for member in members} | {
        mapped[member["uuid"]] for member in members if member["uuid"] in mapped
    }


def group_members(environ, run, group):
    """Args:
        environ: the process environment.
        run: ``subprocess.run`` or a stand-in.
        group: the group id; ``occ group:list`` matches it as a search string and
            prints an empty JSON list when no group matches.

    Returns:
        The accounts of that Nextcloud group.
    """
    found = json.loads(occ(environ, run, "group:list", group, "--output=json")) or {}
    return found.get(group, [])


def provisioned_by_user_oidc(environ, run, account, directory):
    """Args:
        environ: the process environment.
        run: ``subprocess.run`` or a stand-in.
        account: a Nextcloud account.
        directory: the accounts ``user_ldap`` mapped, which ``user_oidc`` signs in to.

    Returns:
        Whether ``user_oidc`` provisions the groups of the account: a directory
        account, or an account of the ``user_oidc`` backend.
    """
    if account in directory:
        return True
    info = json.loads(occ(environ, run, "user:info", account, "--output=json"))
    return info["backend"] == USER_OIDC_BACKEND


def remove_from_group(environ, run, group, account):
    """Args:
        environ: the process environment.
        run: ``subprocess.run`` or a stand-in.
        group: the group id.
        account: the account that leaves the group.
    """
    occ(environ, run, "group:removeuser", group, account)


def revoke_lapsed_groups(environ, run, mapped, roster):
    """Args:
        environ: the process environment.
        run: ``subprocess.run`` or a stand-in.
        mapped: ``{directory uuid: Nextcloud account}`` of every account ``user_ldap`` mapped.
        roster: ``{role: [members]}`` the runner hands over.
    """
    logins = set(json.loads(environ["NEXTCLOUD_RBAC_KEEP"]))
    keep = logins | account_names(
        [member for member in roster[USERS_ROLE] if member["username"] in logins],
        mapped,
    )
    directory = set(mapped.values())
    group_roles = json.loads(environ["NEXTCLOUD_USER_OIDC_GROUP_ROLES"])
    for group, role in sorted(group_roles.items()):
        holders = keep | account_names(roster[role], mapped)
        lapsed = set(group_members(environ, run, group)) - holders
        for account in sorted(lapsed):
            if provisioned_by_user_oidc(environ, run, account, directory):
                remove_from_group(environ, run, group, account)
                print(f"CHANGED {account} left {group}")


def main(environ, run=subprocess.run):
    """Args:
        environ: the process environment.
        run: ``subprocess.run`` or a stand-in.

    Returns:
        0, or 1 when directory members exist but none matches a mapped account.
    """
    occ(environ, run, "user:list", "--output=json", "--limit=0")
    mapped = ldap_accounts(environ, run)
    roster = read_members(environ)
    members = directory_addresses(environ, roster[USERS_ROLE])
    addresses = {
        mapped[uuid]: address for uuid, address in members.items() if uuid in mapped
    }
    if members and not addresses:
        reason = unmatched_reason(
            len(members), len(mapped), environ["NEXTCLOUD_LDAP_USER_LISTING"] == "true"
        )
        if reason:
            print(f"FAILED {reason}", file=sys.stderr)
            return 1
    revoke_lapsed_groups(environ, run, mapped, roster)
    for account in sorted(addresses):
        occ(environ, run, "ldap:check-user", "--update", account)
        if addresses[account] is None:
            continue
        current = occ(
            environ, run, "user:profile", account, "address", "--default-value="
        ).strip()
        if current != addresses[account]:
            occ(environ, run, "user:profile", account, "address", addresses[account])
            print(f"CHANGED {account} address")
    print(f"REFRESHED {len(addresses)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(os.environ))
