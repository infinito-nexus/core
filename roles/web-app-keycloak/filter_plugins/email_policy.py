from ansible.errors import AnsibleFilterError

LEGACY_POLICY = "external"


def kc_held_email_policy(realm, attribute, policies):
    """Return the email policy a realm holds.

    Args:
        realm: realm representation, at least its ``attributes``.
        attribute: realm attribute that records the policy.
        policies: the known policies.

    Returns:
        The recorded policy; ``external`` for a realm without the attribute,
        since every realm created before the attribute keeps the address the
        user brings as primary.

    Raises:
        AnsibleFilterError: the realm records a policy outside ``policies``.
    """
    held = (realm.get("attributes") or {}).get(attribute, LEGACY_POLICY)
    if held not in policies:
        raise AnsibleFilterError(
            f"realm attribute {attribute} is {held!r}; it must be one of "
            f"{', '.join(policies)}."
        )
    return held


def kc_email_policy_change(held, wanted, switch):
    """Return how a deploy moves a realm from its held to the wanted policy.

    Args:
        held: policy the realm holds.
        wanted: policy services.keycloak.email.policy resolves to.
        switch: services.keycloak.email.switch.

    Returns:
        ``keep`` when both agree, ``switch`` for a confirmed move from
        ``external`` to ``mailbox``.

    Raises:
        AnsibleFilterError: the policies differ without a confirmed, supported switch.
    """
    if held == wanted:
        return "keep"
    if switch and held == "external" and wanted == "mailbox":
        return "switch"
    if held == "mailbox":
        raise AnsibleFilterError(
            f"The realm holds the mailbox email policy and the deploy resolves "
            f"'{wanted}'; a mailbox realm cannot return to external addresses. "
            "Set services.keycloak.email.policy to mailbox."
        )
    raise AnsibleFilterError(
        "The realm holds the external email policy and the deploy resolves "
        f"'{wanted}'. Set services.keycloak.email.policy to external to keep "
        "the external addresses, or services.keycloak.email.switch to true to "
        "make every external address the secondary one and every primary "
        "address the mailbox."
    )


def kc_email_sources(captured, inventory):
    """Return the addresses that become secondary addresses, by login.

    Args:
        captured: login to email as Keycloak holds it, read before a switch.
        inventory: login to the inventory's secondary address.

    Returns:
        ``inventory`` overlaid with every non-empty ``captured`` address, so the
        address a user confirmed in Keycloak wins over the inventory.
    """
    sources = {login: address for login, address in inventory.items() if address}
    sources.update({login: address for login, address in captured.items() if address})
    return sources


class FilterModule:
    def filters(self):
        return {
            "kc_held_email_policy": kc_held_email_policy,
            "kc_email_policy_change": kc_email_policy_change,
            "kc_email_sources": kc_email_sources,
        }
