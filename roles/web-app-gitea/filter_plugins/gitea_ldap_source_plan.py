from __future__ import annotations

from ansible.errors import AnsibleFilterError


def gitea_ldap_source_plan(source_ids, user_rows):
    """Pick the one LDAP auth source to keep and the duplicates to delete.

    Args:
        source_ids: IDs of every auth source of the role's LDAP type, as
            ``gitea admin auth list`` prints them.
        user_rows: ``[id, linked]`` rows of ``files/sql/auth-source-users.sql``,
            where ``linked`` counts the users and external logins Gitea checks
            before it deletes a source. Only read when ``source_ids`` holds
            more than one ID.

    Returns:
        ``{"keep": id, "delete": [ids]}``. ``keep`` is ``""`` when no source
        exists, the only source when there is one, else the one source users
        are linked to, else the lowest ID.

    Raises:
        AnsibleFilterError: a listed source has no row in ``user_rows``, or
            users are linked to more than one source.
    """
    ids = sorted({str(source_id).strip() for source_id in source_ids} - {""}, key=int)
    if len(ids) < 2:
        return {"keep": ids[0] if ids else "", "delete": []}
    linked = {str(row[0]).strip(): int(row[1]) for row in user_rows}
    missing = [source_id for source_id in ids if source_id not in linked]
    if missing:
        raise AnsibleFilterError(
            f"gitea_ldap_source_plan: the database holds no login_source row for "
            f"the listed LDAP source id(s) {', '.join(missing)}; the query did not "
            f"reach Gitea's database, so no source is deleted"
        )
    in_use = [source_id for source_id in ids if linked[source_id] > 0]
    if len(in_use) > 1:
        counts = ", ".join(
            f"id {source_id}: {linked[source_id]} linked" for source_id in in_use
        )
        raise AnsibleFilterError(
            f"gitea_ldap_source_plan: users are linked to {len(in_use)} LDAP auth "
            f"sources ({counts}). Gitea refuses to delete a source in use and the "
            f"role keeps exactly one, so move every user of all but one of them to "
            f"the remaining source (Site Administration > User Accounts > Edit > "
            f"Authentication Source), then deploy again"
        )
    keep = in_use[0] if in_use else ids[0]
    return {
        "keep": keep,
        "delete": [source_id for source_id in ids if source_id != keep],
    }


class FilterModule:
    def filters(self):
        return {"gitea_ldap_source_plan": gitea_ldap_source_plan}
