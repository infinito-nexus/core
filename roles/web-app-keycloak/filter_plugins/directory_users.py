from ansible.errors import AnsibleFilterError


def kc_directory_users(listings, usernames):
    """Return one directory entry per Keycloak user the kcadm listings hold.

    Args:
        listings: the parsed output of each ``kcadm get users`` call, each a list
            of user representations reduced to ``id,username,email,emailVerified``.
        usernames: the requested usernames; empty keeps every user, otherwise
            only the users whose username equals one of them, compared
            case-insensitively because Keycloak stores usernames lowercased.

    Returns:
        A ``{username, email, emailVerified, id}`` mapping per user, in listing
        order, once per id even when two pages overlap. ``id`` is the user id
        Keycloak's ``oidc-sub-mapper`` emits as the OIDC ``sub``. ``email`` is
        empty for a user without one, because Keycloak leaves a null address
        out of the representation.

    Raises:
        AnsibleFilterError: a listing is not a list of user representations.
    """
    wanted = {name.lower() for name in usernames}
    seen = set()
    entries = []
    for listing in listings:
        if not isinstance(listing, list):
            raise AnsibleFilterError(
                f"kc_directory_users: a kcadm listing is {type(listing).__name__}, not a list of users."
            )
        for user in listing:
            try:
                entry = {
                    "username": user["username"],
                    "email": user.get("email", ""),
                    "emailVerified": user["emailVerified"],
                    "id": user["id"],
                }
            except (KeyError, TypeError, AttributeError) as error:
                raise AnsibleFilterError(
                    f"kc_directory_users: a kcadm user lacks {error}; the call must request "
                    "--fields id,username,email,emailVerified."
                ) from None
            if wanted and entry["username"].lower() not in wanted:
                continue
            if entry["id"] in seen:
                continue
            seen.add(entry["id"])
            entries.append(entry)
    return entries


class FilterModule:
    def filters(self):
        return {"kc_directory_users": kc_directory_users}
