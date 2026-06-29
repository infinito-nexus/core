#!/bin/bash
# Configure Checkmk header-auth (for the oauth2-proxy gate) and the central
# OpenLDAP connection inside the running site. Invoked from the role via
# `container exec -i <name> bash -s` with the CMK_*/LDAP_* values passed as env.
#
# Structure verified against the Checkmk v2.4.0p32 source:
#   - auth_by_http_header stores the trusted header NAME (cmk/gui/auth.py).
#   - user connections persist in etc/check_mk/multisite.d/wato/user_connections.mk
#     as the `user_connections` list (cmk/gui/userdb/_connections.py).
#   - directory_type for OpenLDAP is ("openldap", {"connect_to": ("fixed_list", …)})
#     (cmk/gui/userdb/ldap_connector.py).
# Header-auth does NOT auto-create users, so the LDAP connection must sync them;
# the site background job performs the initial sync shortly after the reload.
# Each generated .mk is Python-syntax-checked before the Apache reload so a typo
# cannot leave the GUI in a 500 state.
set -euo pipefail

SITE="${CMK_SITE_ID:-cmk}"
CFG="/omd/sites/${SITE}/etc/check_mk/multisite.d"
mkdir -p "${CFG}/wato"

if [ "${CHECKMK_SSO_ENABLED:-false}" = "true" ]; then
  cat > "${CFG}/zzz_infinito_sso.mk" <<'EOF'
# Managed by web-app-checkmk (Infinito.Nexus). Trust the username supplied by
# the upstream oauth2-proxy gate (nginx sets X-Remote-User after Keycloak auth).
auth_by_http_header = "X-Remote-User"
EOF
  python3 -c "exec(open('${CFG}/zzz_infinito_sso.mk').read())"
fi

if [ "${CHECKMK_LDAP_ENABLED:-false}" = "true" ]; then
  cat > "${CFG}/wato/user_connections.mk" <<EOF
# Managed by web-app-checkmk (Infinito.Nexus). Central OpenLDAP connection.
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
