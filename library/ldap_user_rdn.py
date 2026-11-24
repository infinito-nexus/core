"""Args:
    server_uri: LDAP server URI.
    bind_dn: DN to bind as.
    bind_pw: password of bind_dn.
    renames: list of {dn, new_rdn, move, references}; with move the entry at
        dn moves to new_rdn and drops its old RDN value, then every item of
        references ({dn, attribute, old, new}) gets new added to attribute of
        the group at dn before old is deleted from it, so a group never runs
        empty. A value already added or already deleted counts as done.

Returns:
    renamed_dns: the DNs that moved.
    rewritten: one {dn, attribute} per group value that was repointed.
"""

import contextlib
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
    "renames": {
        "type": "list",
        "elements": "dict",
        "required": True,
        "options": {
            "dn": {"type": "str", "required": True},
            "new_rdn": {"type": "str", "required": True},
            "move": {"type": "bool", "required": True},
            "references": {
                "type": "list",
                "elements": "dict",
                "required": True,
                "options": {
                    "dn": {"type": "str", "required": True},
                    "attribute": {"type": "str", "required": True},
                    "old": {"type": "str", "required": True},
                    "new": {"type": "str", "required": True},
                },
            },
        },
    },
}


def repoint(conn, reference):
    """Args:
        conn: the bound LDAP connection.
        reference: one {dn, attribute, old, new} item of a rename's references.
    """
    name = reference["attribute"]
    with contextlib.suppress(ldap.TYPE_OR_VALUE_EXISTS):
        conn.modify_s(
            reference["dn"],
            [(ldap.MOD_ADD, name, [reference["new"].encode("utf-8")])],
        )
    with contextlib.suppress(ldap.NO_SUCH_ATTRIBUTE):
        conn.modify_s(
            reference["dn"],
            [(ldap.MOD_DELETE, name, [reference["old"].encode("utf-8")])],
        )


def migrate(conn, renames, check_mode, result):
    """Args:
        conn: the bound LDAP connection.
        renames: the renames parameter.
        check_mode: report the work without writing.
        result: dict whose renamed_dns and rewritten lists collect the work done.
    """
    for rename in renames:
        if rename["move"]:
            if not check_mode:
                conn.rename_s(rename["dn"], rename["new_rdn"], delold=1)
            result["renamed_dns"].append(rename["dn"])
        for reference in rename["references"]:
            if not check_mode:
                repoint(conn, reference)
            result["rewritten"].append(
                {"dn": reference["dn"], "attribute": reference["attribute"]}
            )


def main():
    module = AnsibleModule(argument_spec=ARGUMENT_SPEC, supports_check_mode=True)
    if ldap is None:
        module.fail_json(
            msg=missing_required_lib("python-ldap"), exception=LDAP_IMPORT_ERROR
        )
    params = module.params
    result = {"renamed_dns": [], "rewritten": []}
    try:
        conn = ldap.initialize(params["server_uri"])
        conn.set_option(ldap.OPT_REFERRALS, 0)
        conn.simple_bind_s(params["bind_dn"], params["bind_pw"])
        migrate(conn, params["renames"], module.check_mode, result)
    except ldap.LDAPError as error:
        module.fail_json(msg=f"LDAP rename failed: {error}", **result)
    module.exit_json(
        changed=bool(result["renamed_dns"] or result["rewritten"]), **result
    )


if __name__ == "__main__":
    main()
