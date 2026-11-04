#!/bin/bash
set -euo pipefail

SITE="${CMK_SITE_ID:-cmk}"
CFG="/omd/sites/${SITE}/etc/check_mk/multisite.d"
mkdir -p "${CFG}/wato"

if [ "${CHECKMK_SSO_ENABLED:-false}" = "true" ]; then
  cat > "${CFG}/zzz_infinito_sso.mk" <<'EOF'
auth_by_http_header = "X-Remote-User"
EOF
  python3 -c "exec(open('${CFG}/zzz_infinito_sso.mk').read())"
fi

if [ "${CHECKMK_LDAP_ENABLED:-false}" = "true" ]; then
  cat > "${CFG}/wato/user_connections.mk" <<EOF
user_connections = [
    {
        "id": "ldap_infinito",
        "type": "ldap",
        "description": "Infinito.Nexus OpenLDAP",
        "comment": "Managed by web-app-checkmk",
        "docu_url": "",
        "disabled": False,
        "directory_type": (
            "openldap",
            {"connect_to": ("fixed_list", {"server": "${LDAP_SERVER}", "port": ${LDAP_PORT}})},
        ),
        "bind": ("${LDAP_BIND_DN}", ("password", "${LDAP_BIND_PASSWORD}")),
        "user_dn": "${LDAP_USER_DN}",
        "user_scope": "sub",
        "user_id": "${LDAP_UID_ATTR}",
        "user_id_umlauts": "keep",
        "user_filter": "${LDAP_USER_FILTER}",
        "group_dn": "${LDAP_GROUP_DN}",
        "group_scope": "sub",
        "group_member": "member",
        "active_plugins": {
            "email": {},
            "alias": {},
            "pager": {"attr": "${LDAP_PAGER_ATTR}"},
            "groups_to_roles": {
                "admin": [("${LDAP_ROLE_ADMIN_DN}", None)],
                "user": [("${LDAP_ROLE_USER_DN}", None)],
                "guest": [("${LDAP_ROLE_GUEST_DN}", None)],
            },
        },
        "cache_livetime": 300,
        "version": 3,
    }
]
EOF
  python3 -c "exec(open('${CFG}/wato/user_connections.mk').read())"
  rm -f "/omd/sites/${SITE}/var/check_mk/web/ldap_ldap_infinito_sync_time.mk"
fi

chown -R "${SITE}:${SITE}" "${CFG}"
su - "${SITE}" -c "omd reload apache" || su - "${SITE}" -c "omd restart apache"
