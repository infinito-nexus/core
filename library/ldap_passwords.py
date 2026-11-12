"""Set LDAP passwords over one connection, like community.general.ldap_passwd.

Args:
    server_uri: LDAP server URI.
    bind_dn: DN to bind as.
    bind_pw: password of bind_dn.
    entries: list of {dn, passwd}; an entry whose passwd already binds is left
        alone, every other entry gets passwd through the password modify
        extended operation.

Returns:
    changed_dns: the DNs whose password was set.
    failed_dns: the DNs whose bind check or password change failed.
"""

import traceback

from ansible.module_utils.basic import AnsibleModule, missing_required_lib

try:
    import ldap
except ImportError:
    ldap = None
    LDAP_IMPORT_ERROR = traceback.format_exc()
else:
    LDAP_IMPORT_ERROR = None

ARGUMENT_SPEC = {
    "server_uri": {"type": "str", "required": True},
    "bind_dn": {"type": "str", "required": True},
    "bind_pw": {"type": "str", "required": True, "no_log": True},
    "entries": {
        "type": "list",
        "elements": "dict",
        "required": True,
        "options": {
            "dn": {"type": "str", "required": True},
            "passwd": {"type": "str", "required": True, "no_log": True},
        },
    },
}


def needs_change(server_uri, dn, passwd):
    probe = ldap.initialize(server_uri)
    try:
        probe.simple_bind_s(dn, passwd)
    except ldap.INVALID_CREDENTIALS:
        return True
    finally:
        probe.unbind()
    return False


def converge(conn, server_uri, entries, check_mode):
    changed_dns = []
    errors = {}
    for entry in entries:
        dn = entry["dn"]
        try:
            if not needs_change(server_uri, dn, entry["passwd"]):
                continue
        except ldap.LDAPError as error:
            errors[dn] = f"Cannot bind to the server as {dn}: {error}"
            continue
        if not check_mode:
            try:
                conn.passwd_s(dn, None, entry["passwd"])
            except ldap.LDAPError as error:
                errors[dn] = f"Unable to set the password of {dn}: {error}"
                continue
        changed_dns.append(dn)
    return changed_dns, errors


def main():
    module = AnsibleModule(argument_spec=ARGUMENT_SPEC, supports_check_mode=True)
    if ldap is None:
        module.fail_json(
            msg=missing_required_lib("python-ldap"), exception=LDAP_IMPORT_ERROR
        )
    params = module.params
    try:
        conn = ldap.initialize(params["server_uri"])
        conn.set_option(ldap.OPT_REFERRALS, 0)
        conn.simple_bind_s(params["bind_dn"], params["bind_pw"])
    except ldap.LDAPError as error:
        module.fail_json(msg=f"Cannot bind to the server: {error}")
    changed_dns, errors = converge(
        conn, params["server_uri"], params["entries"], module.check_mode
    )
    if errors:
        module.fail_json(
            msg="; ".join(errors.values()),
            changed=bool(changed_dns),
            changed_dns=changed_dns,
            failed_dns=list(errors),
        )
    module.exit_json(changed=bool(changed_dns), changed_dns=changed_dns, failed_dns=[])


if __name__ == "__main__":
    main()
