#!/usr/bin/env bash
#
# Output: one line per schema, entry or ACL grant it added; nothing when all exist.
#
# Required env, supplied via `container exec -e KEY`:
#   FD_ADMIN_DN                DN of the platform administrator persona's entry
#   FD_ADMINISTRATOR_GROUP_DN  RBAC group granted the admin ACL role
#   FD_USER_MANAGER_GROUP_DN   RBAC group granted the user-manager ACL role
#   FD_SELF_SERVICE_GROUP_DN   RBAC group granted the self-service ACL role
#   FD_GROUP_RDN               RDN of the groups branch (e.g. ou=groups)
#   FD_HTTP_HEADER_NAME        $_SERVER key suffix of the identity header (e.g. X_FORWARDED_PREFERRED_USERNAME)
#   FD_LOGIN_ATTRIBUTE         attribute a login name is matched against (e.g. uid)
#   FD_LOGIN_METHOD            FusionDirectory login method (LoginPost or LoginHTTPHeader)
#   FD_TIMEZONE                timezone FusionDirectory renders dates in
#   FD_USER_RDN                RDN of the users branch (e.g. ou=users)
# Required env, set by the container's env file:
#   LDAP01_HOST, LDAP01_PORT, LDAP01_BASE_DN, LDAP01_ADMIN_DN, LDAP01_ADMIN_PASS
set -euo pipefail

uri="ldap://${LDAP01_HOST}:${LDAP01_PORT}"
base="${LDAP01_BASE_DN}"
schema_dir=/www/fusiondirectory/contrib/openldap
aclroles="ou=aclroles,${base}"
admin_role_dn="cn=admin,${aclroles}"
user_manager_role_dn="cn=user-manager,${aclroles}"
self_service_role_dn="cn=self-service,${aclroles}"
config_dn="cn=config,ou=fusiondirectory,${base}"

ldap() {
  local tool="$1"
  shift
  "$tool" -x -H "$uri" -D "$LDAP01_ADMIN_DN" -y <(printf %s "$LDAP01_ADMIN_PASS") "$@"
}

found() {
  [ "$(ldap ldapsearch -LLL -o ldif-wrap=no -b "$1" -s base "(objectClass=*)" dn 2>/dev/null | grep -c '^dn:')" -gt 0 ]
}

add_absent() {
  local dn="$1"
  local ldif
  ldif="$(cat)"
  if found "$dn"; then
    return 0
  fi
  ldap ldapadd >/dev/null <<<"$ldif"
  echo "added ${dn}"
}

b64() {
  printf %s "$1" | base64 | tr -d '\n'
}

add_role() {
  local dn="$1" cn="$2" description="$3" template="$4"
  add_absent "$dn" <<LDIF
dn: ${dn}
objectClass: top
objectClass: gosaRole
cn: ${cn}
description: ${description}
gosaAclTemplate: ${template}
LDIF
}

grant() {
  local role="$1" member="$2"
  local acl base_entry
  acl=":subtree:$(b64 "$role"):$(b64 "$member")"
  base_entry="$(ldap ldapsearch -LLL -o ldif-wrap=no -b "$base" -s base "(objectClass=*)" objectClass gosaAclEntry)"
  if grep -q -F "$acl" <<<"$base_entry"; then
    return 0
  fi
  {
    echo "dn: ${base}"
    echo "changetype: modify"
    if ! grep -q -i -x 'objectClass: gosaAcl' <<<"$base_entry"; then
      echo "add: objectClass"
      echo "objectClass: gosaAcl"
      echo "-"
    fi
    echo "add: gosaAclEntry"
    echo "gosaAclEntry: $(grep -c '^gosaAclEntry:' <<<"$base_entry")${acl}"
  } | ldap ldapmodify >/dev/null
  echo "granted ${role} to ${member}"
}

reconcile() {
  local dn="$1" attribute="$2" value="$3"
  local current
  current="$(ldap ldapsearch -LLL -o ldif-wrap=no -b "$dn" -s base "(objectClass=*)" "$attribute")"
  if grep -q -x -F "${attribute}: ${value}" <<<"$current"; then
    return 0
  fi
  printf 'dn: %s\nchangetype: modify\nreplace: %s\n%s: %s\n' "$dn" "$attribute" "$attribute" "$value" | ldap ldapmodify >/dev/null
  echo "set ${attribute} of ${dn} to ${value}"
}

loaded="$(ldap ldapsearch -LLL -o ldif-wrap=no -b cn=schema,cn=config -s one dn)"
for schema in core-fd core-fd-conf ldapns template-fd; do
  if ! grep -q -E "^dn: cn=\{[0-9]+\}${schema}," <<<"$loaded"; then
    schema2ldif "${schema_dir}/${schema}.schema" | ldap ldapadd >/dev/null
    echo "inserted schema ${schema}"
  fi
done

add_absent "$aclroles" <<LDIF
dn: ${aclroles}
objectClass: organizationalUnit
ou: aclroles
LDIF

add_role "$admin_role_dn" admin "Gives all rights on all objects" "0:all;cmdrw"
add_role "$user_manager_role_dn" user-manager "Gives all rights on users in the given branch" "0:user/user;cmdrw,user/posixAccount;cmdrw"
add_role "$self_service_role_dn" self-service "Allows users to edit their own information" "0:user/user;srw,user/posixAccount;srw"

grant "$admin_role_dn" "$FD_ADMIN_DN"
grant "$admin_role_dn" "$FD_ADMINISTRATOR_GROUP_DN"
grant "$user_manager_role_dn" "$FD_USER_MANAGER_GROUP_DN"
grant "$self_service_role_dn" "$FD_SELF_SERVICE_GROUP_DN"

add_absent "ou=fusiondirectory,${base}" <<LDIF
dn: ou=fusiondirectory,${base}
objectClass: organizationalUnit
ou: fusiondirectory
LDIF

add_absent "$config_dn" <<LDIF
dn: ${config_dn}
objectClass: fusionDirectoryConf
objectClass: fusionDirectoryPluginsConf
cn: config
fdTheme: breezy
fdTimezone: ${FD_TIMEZONE}
fdLoginAttribute: ${FD_LOGIN_ATTRIBUTE}
fdLoginMethod: ${FD_LOGIN_METHOD}
fdHttpHeaderAuthHeaderName: ${FD_HTTP_HEADER_NAME}
fdAccountPrimaryAttribute: ${FD_LOGIN_ATTRIBUTE}
fdUserRDN: ${FD_USER_RDN}
fdGroupRDN: ${FD_GROUP_RDN}
fdOGroupRDN: ${FD_GROUP_RDN}
fdAclRoleRDN: ou=aclroles
fdCnPattern: %givenName% %sn%
fdGivenNameRequired: TRUE
fdStrictNamingRules: TRUE
fdPasswordDefaultHash: ssha
fdForcePasswordDefaultHash: FALSE
fdModificationDetectionAttribute: entryCSN
fdLdapSizeLimit: 200
fdForceSSL: FALSE
fdWarnSSL: TRUE
fdSchemaCheck: TRUE
fdLogging: TRUE
fdDisplayErrors: FALSE
fdListSummary: TRUE
fdSessionLifeTime: 3600
fdEnableSnapshots: TRUE
fdEnableAutomaticSnapshots: FALSE
fdSnapshotBase: ou=snapshots,${base}
fdIdAllocationMethod: traditional
fdMinId: 100
fdUidNumberBase: 1100
fdGidNumberBase: 1100
LDIF

reconcile "$config_dn" fdLoginMethod "$FD_LOGIN_METHOD"
reconcile "$config_dn" fdHttpHeaderAuthHeaderName "$FD_HTTP_HEADER_NAME"

add_absent "ou=locks,ou=fusiondirectory,${base}" <<LDIF
dn: ou=locks,ou=fusiondirectory,${base}
objectClass: organizationalUnit
ou: locks
LDIF

add_absent "ou=snapshots,${base}" <<LDIF
dn: ou=snapshots,${base}
objectClass: organizationalUnit
ou: snapshots
LDIF
