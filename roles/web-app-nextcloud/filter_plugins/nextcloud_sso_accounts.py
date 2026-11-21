import json

_MARKER = "SSO_ACCOUNTS "
_PLUGINS = ("sociallogin", "user_oidc", "oidc_login")
_MAPPED = ("updated", "unchanged")
_UNMAPPED = {
    "conflict": "holds the user id {held} already",
    "taken": "would share it with the user whose username it is",
    "missing": "is absent from the realm",
    "dropped": "kept no user id",
    "failed": "could not be given the user id",
}


def _accounts(probe_result, caller):
    states = [
        json.loads(line[len(_MARKER) :])
        for line in (probe_result.get("stdout") or "").splitlines()
        if line.startswith(_MARKER)
    ]
    if len(states) != 1:
        raise ValueError(
            f"{caller} expects one {_MARKER.strip()} line, found {len(states)}"
        )
    return states[0]


def _sociallogin_accounts(sociallogin):
    providers = sorted(sociallogin["providers"], key=len, reverse=True)

    def sub_of(key):
        return next(
            (key[len(name) + 1 :] for name in providers if key.startswith(f"{name}-")),
            None,
        )

    found = [
        (uid, "created by sociallogin", sub_of(uid)) for uid in sociallogin["created"]
    ]
    found += [
        (row["uid"], f"connected to {row['identifier']}", sub_of(row["identifier"]))
        for row in sociallogin["connected"]
    ]
    return [(uid, origin, sub) for uid, origin, sub in found if sub is not None]


def nextcloud_sociallogin_subjects(probe_result):
    """
    Args:
      probe_result: registered result of files/php/utils/sso_accounts.php.

    Returns:
      One ``{"id": <sub>, "value": <uid>}`` mapping per account sociallogin
      created or connected under one of its providers: the Keycloak user the
      provider's longest matching ``<provider>-`` prefix names, and the
      Nextcloud user id it signs in to.

    Raises:
      ValueError: stdout holds no single ``SSO_ACCOUNTS`` line.
    """
    accounts = _accounts(probe_result, "nextcloud_sociallogin_subjects")
    return [
        {"id": sub, "value": uid}
        for uid, _, sub in _sociallogin_accounts(accounts["sociallogin"])
    ]


def nextcloud_rekeyed_accounts(probe_result, target, ldap_enabled, attribute_results):
    """
    Args:
      probe_result: registered result of files/php/utils/sso_accounts.php. Its
        stdout holds one ``SSO_ACCOUNTS`` JSON line: the sociallogin
        ``providers``, the ``created`` user ids carrying sociallogin's account
        marker and the ``connected`` ``uid``/``identifier`` rows, plus the
        ``user_oidc`` and ``ldap`` user ids of those backends.
      target: the OIDC plugin the deploy switches to.
      ldap_enabled: whether user_ldap stays on after the switch.
      attribute_results: ``keycloak_user_attribute_results`` of the write of
        ``nextcloud_sociallogin_subjects`` into the uid claim of user_oidc;
        only a switch to user_oidc reads it.

    Returns:
      Sorted labels of the accounts whose owner signs in under another user id
      after the switch, ``<uid> (created by sociallogin)``,
      ``<uid> (connected to <identifier>)``, ``<uid> (user_oidc account)`` or
      ``<uid> (LDAP account)``; a sociallogin account whose Keycloak user did
      not take its user id adds ``Keycloak user <sub>`` and the reason.
      Empty when the switch keeps every account.

    Raises:
      ValueError: target is no OIDC plugin, or stdout holds no single
        ``SSO_ACCOUNTS`` line.
    """
    if target not in _PLUGINS:
        raise ValueError(
            f"nextcloud_rekeyed_accounts: {target!r} is none of {', '.join(_PLUGINS)}"
        )
    accounts = _accounts(probe_result, "nextcloud_rekeyed_accounts")
    written = (
        {(result["id"], result["value"]): result for result in attribute_results}
        if target == "user_oidc"
        else {}
    )
    labels = []
    if target != "sociallogin":
        for uid, origin, sub in _sociallogin_accounts(accounts["sociallogin"]):
            result = written.get((sub, uid))
            if result is None:
                labels.append(f"{uid} ({origin})")
            elif result["outcome"] not in _MAPPED:
                reason = _UNMAPPED[result["outcome"]].format(
                    held=", ".join(result["held"])
                )
                labels.append(f"{uid} ({origin}, Keycloak user {sub} {reason})")
    if target != "user_oidc":
        labels += [f"{uid} (user_oidc account)" for uid in accounts["user_oidc"]]
    if target == "sociallogin" or not ldap_enabled:
        labels += [f"{uid} (LDAP account)" for uid in accounts["ldap"]]
    return sorted(labels)


class FilterModule:
    def filters(self):
        return {
            "nextcloud_rekeyed_accounts": nextcloud_rekeyed_accounts,
            "nextcloud_sociallogin_subjects": nextcloud_sociallogin_subjects,
        }
