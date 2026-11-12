import json

_MARKER = "SSO_ACCOUNTS "
_PLUGINS = ("sociallogin", "user_oidc", "oidc_login")


def nextcloud_rekeyed_accounts(probe_result, target, ldap_enabled):
    """
    Args:
      probe_result: registered result of files/php/utils/sso_accounts.php. Its
        stdout holds one ``SSO_ACCOUNTS`` JSON line: the sociallogin
        ``providers``, the ``created`` user ids carrying sociallogin's account
        marker and the ``connected`` ``uid``/``identifier`` rows, plus the
        ``user_oidc`` and ``ldap`` user ids of those backends.
      target: the OIDC plugin the deploy switches to.
      ldap_enabled: whether user_ldap stays on after the switch.

    Returns:
      Sorted labels of the accounts whose owner signs in under another user id
      after the switch, ``<uid> (created by sociallogin)``,
      ``<uid> (connected to <identifier>)``, ``<uid> (user_oidc account)`` or
      ``<uid> (LDAP account)``; empty when the switch keeps every account.

    Raises:
      ValueError: target is no OIDC plugin, or stdout holds no single
        ``SSO_ACCOUNTS`` line.
    """
    if target not in _PLUGINS:
        raise ValueError(
            f"nextcloud_rekeyed_accounts: {target!r} is none of {', '.join(_PLUGINS)}"
        )
    states = [
        json.loads(line[len(_MARKER) :])
        for line in (probe_result.get("stdout") or "").splitlines()
        if line.startswith(_MARKER)
    ]
    if len(states) != 1:
        raise ValueError(
            f"nextcloud_rekeyed_accounts expects one {_MARKER.strip()} line, "
            f"found {len(states)}"
        )
    accounts = states[0]
    sociallogin = accounts["sociallogin"]
    prefixes = tuple(f"{name}-" for name in sociallogin["providers"])
    labels = []
    if target != "sociallogin":
        labels += [
            f"{uid} (created by sociallogin)"
            for uid in sociallogin["created"]
            if uid.startswith(prefixes)
        ]
        labels += [
            f"{row['uid']} (connected to {row['identifier']})"
            for row in sociallogin["connected"]
            if row["identifier"].startswith(prefixes)
        ]
    if target != "user_oidc":
        labels += [f"{uid} (user_oidc account)" for uid in accounts["user_oidc"]]
    if target == "sociallogin" or not ldap_enabled:
        labels += [f"{uid} (LDAP account)" for uid in accounts["ldap"]]
    return sorted(labels)


class FilterModule:
    def filters(self):
        return {"nextcloud_rekeyed_accounts": nextcloud_rekeyed_accounts}
