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
        "group_dn": "${LDAP_GROUP_DN}",
        "group_scope": "sub",
        "group_member": "member",
        "active_plugins": {"email": {}, "alias": {}},
        "cache_livetime": 300,
        "version": 3,
    }
]
EOF
  python3 -c "exec(open('${CFG}/wato/user_connections.mk').read())"
fi

chown -R "${SITE}:${SITE}" "${CFG}"
su - "${SITE}" -c "omd reload apache" || su - "${SITE}" -c "omd restart apache"
