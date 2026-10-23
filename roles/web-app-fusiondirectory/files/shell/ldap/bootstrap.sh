#!/usr/bin/env bash
#
# Output: one line per schema, entry or ACL grant it added; nothing when all exist.
#
# Required env, supplied via `container exec -e KEY`:
#   FD_ADMIN_DN    DN of the platform administrator persona's entry
#   FD_GROUP_RDN   RDN of the groups branch (e.g. ou=groups)
#   FD_TIMEZONE    timezone FusionDirectory renders dates in
#   FD_USER_RDN    RDN of the users branch (e.g. ou=users)
# Required env, set by the container's env file:
#   LDAP01_HOST, LDAP01_PORT, LDAP01_BASE_DN, LDAP01_ADMIN_DN, LDAP01_ADMIN_PASS
set -euo pipefail

uri="ldap://${LDAP01_HOST}:${LDAP01_PORT}"
base="${LDAP01_BASE_DN}"
schema_dir=/www/fusiondirectory/contrib/openldap
role_dn="cn=admin,ou=aclroles,${base}"

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

loaded="$(ldap ldapsearch -LLL -o ldif-wrap=no -b cn=schema,cn=config -s one dn)"
for schema in core-fd core-fd-conf ldapns template-fd; do
  if ! grep -q -E "^dn: cn=\{[0-9]+\}${schema}," <<<"$loaded"; then
    schema2ldif "${schema_dir}/${schema}.schema" | ldap ldapadd >/dev/null
    echo "inserted schema ${schema}"
  fi
done

add_absent "ou=aclroles,${base}" <<LDIF
dn: ou=aclroles,${base}
objectClass: organizationalUnit
ou: aclroles
LDIF

add_absent "$role_dn" <<LDIF
dn: ${role_dn}
objectClass: top
objectClass: gosaRole
cn: admin
description: Gives all rights on all objects
gosaAclTemplate: 0:all;cmdrw
LDIF

acl=":subtree:$(b64 "$role_dn"):$(b64 "$FD_ADMIN_DN")"
base_entry="$(ldap ldapsearch -LLL -o ldif-wrap=no -b "$base" -s base "(objectClass=*)" objectClass gosaAclEntry)"
if ! grep -q -F "$acl" <<<"$base_entry"; then
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
  echo "granted ${role_dn} to ${FD_ADMIN_DN}"
fi

add_absent "ou=fusiondirectory,${base}" <<LDIF
dn: ou=fusiondirectory,${base}
objectClass: organizationalUnit
ou: fusiondirectory
LDIF

add_absent "cn=config,ou=fusiondirectory,${base}" <<LDIF
dn: cn=config,ou=fusiondirectory,${base}
objectClass: fusionDirectoryConf
objectClass: fusionDirectoryPluginsConf
cn: config
fdTheme: breezy
fdTimezone: ${FD_TIMEZONE}
fdLoginAttribute: uid
fdLoginMethod: LoginPost
fdAccountPrimaryAttribute: uid
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
