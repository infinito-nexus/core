"""Create LDAP entries or converge their attributes over one connection.

Args:
    server_uri: LDAP server URI.
    bind_dn: DN to bind as.
    bind_pw: password of bind_dn.
    state: create adds every missing entry and leaves existing ones alone,
        like community.general.ldap_entry; present adds the attribute values
        an entry lacks and exact makes each listed attribute hold exactly the
        given values, like community.general.ldap_attrs.
    entries: list of {dn, attributes}; attributes maps a name to a value or a
        list of values.

Returns:
    changed_dns: the DNs that were created or modified.
"""

import traceback

from ansible.module_utils.basic import AnsibleModule, missing_required_lib

try:
    import ldap
    import ldap.filter
    import ldap.modlist
except ImportError:
    ldap = None
    LDAP_IMPORT_ERROR = traceback.format_exc()
else:
    LDAP_IMPORT_ERROR = None

ARGUMENT_SPEC = {
    "server_uri": {"type": "str", "required": True},
    "bind_dn": {"type": "str", "required": True},
    "bind_pw": {"type": "str", "required": True, "no_log": True},
    "state": {
        "type": "str",
        "required": True,
        "choices": ["create", "present", "exact"],
    },
    "entries": {
        "type": "list",
        "elements": "dict",
        "required": True,
        "options": {
            "dn": {"type": "str", "required": True},
            "attributes": {"type": "dict", "required": True},
        },
    },
}


def encode(value):
    items = value if isinstance(value, list) else [value]
    return [str(item).encode("utf-8") for item in items]


def exists(conn, dn):
    try:
        conn.search_s(dn, ldap.SCOPE_BASE, attrlist=["1.1"])
    except ldap.NO_SUCH_OBJECT:
        return False
    return True


def has_value(conn, dn, name, value):
    escaped = ldap.filter.escape_filter_chars(value.decode("utf-8"))
    try:
        return len(conn.search_s(dn, ldap.SCOPE_BASE, f"({name}={escaped})")) == 1
    except ldap.NO_SUCH_OBJECT:
        return False


def current_values(conn, dn, name):
    found = conn.search_s(dn, ldap.SCOPE_BASE, attrlist=[name])[0][1]
    for key, values in found.items():
        if key.lower() == name.lower():
            return values
    return []


def present_changes(conn, dn, attributes):
    changes = []
    for name, value in attributes.items():
        missing = [v for v in encode(value) if not has_value(conn, dn, name, v)]
        if missing:
            changes.append((ldap.MOD_ADD, name, missing))
    return changes


def exact_changes(conn, dn, attributes):
    changes = []
    for name, value in attributes.items():
        wanted = encode(value)
        current = current_values(conn, dn, name)
        if frozenset(wanted) == frozenset(current):
            continue
        if not current:
            changes.append((ldap.MOD_ADD, name, wanted))
        elif not wanted:
            changes.append((ldap.MOD_DELETE, name, None))
        else:
            changes.append((ldap.MOD_REPLACE, name, wanted))
    return changes


def apply(conn, state, dn, attributes, check_mode):
    if state == "create":
        if exists(conn, dn):
            return False
        if not check_mode:
            encoded = {name: encode(value) for name, value in attributes.items()}
            conn.add_s(dn, ldap.modlist.addModlist(encoded))
        return True
    changes = (present_changes if state == "present" else exact_changes)(
        conn, dn, attributes
    )
    if changes and not check_mode:
        conn.modify_s(dn, changes)
    return bool(changes)


def main():
    module = AnsibleModule(argument_spec=ARGUMENT_SPEC, supports_check_mode=True)
    if ldap is None:
        module.fail_json(
            msg=missing_required_lib("python-ldap"), exception=LDAP_IMPORT_ERROR
        )
    params = module.params
    changed_dns = []
    try:
        conn = ldap.initialize(params["server_uri"])
        conn.set_option(ldap.OPT_REFERRALS, 0)
        conn.simple_bind_s(params["bind_dn"], params["bind_pw"])
        changed_dns.extend(
            entry["dn"]
            for entry in params["entries"]
            if apply(
                conn,
                params["state"],
                entry["dn"],
                entry["attributes"],
                module.check_mode,
            )
        )
    except ldap.LDAPError as error:
        module.fail_json(
            msg=f"LDAP {params['state']} failed: {error}", changed_dns=changed_dns
        )
    module.exit_json(changed=bool(changed_dns), changed_dns=changed_dns)


if __name__ == "__main__":
    main()
