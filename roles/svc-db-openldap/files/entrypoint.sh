#!/usr/bin/env bash
set -euo pipefail

: "${LDAP_SUFFIX:?LDAP_SUFFIX must be set (e.g. dc=infinito,dc=example)}"
: "${LDAP_ROOT_DN:?LDAP_ROOT_DN must be set (e.g. cn=administrator,dc=infinito,dc=example)}"
: "${LDAP_ROOT_PW:?LDAP_ROOT_PW must be set}"
: "${LDAP_LOG_LEVEL:?LDAP_LOG_LEVEL must be set (e.g. stats, stats2, acl, 0)}"

SLAPD_D_DIR="/etc/ldap/slapd.d"
DB_DIR="/var/lib/ldap"
TMP_CONF="/tmp/slapd.conf"

log() { echo "[openldap] $*"; }
fatal() { echo "[openldap][FATAL] $*" >&2; exit 1; }

bootstrap_needed() {
  [ ! -d "${SLAPD_D_DIR}" ] || [ -z "$(ls -A "${SLAPD_D_DIR}" 2>/dev/null)" ]
}

has_cn_config() {
  [ -d "${SLAPD_D_DIR}/cn=config" ]
}

has_mdb_files() {
  [ -f "${DB_DIR}/data.mdb" ] || [ -f "${DB_DIR}/data.mdb.lock" ]
}

detect_module_path() {
  if [ -d /usr/lib/ldap ]; then
    echo "/usr/lib/ldap"
    return 0
  fi
  local p
  p="$(find /usr/lib -maxdepth 2 -type d -name ldap 2>/dev/null | head -n 1 || true)"
  if [ -n "${p}" ] && [ -d "${p}" ]; then
    echo "${p}"
    return 0
  fi
  echo "/usr/lib/ldap"
}

detect_schema_dir() {
  if [ -d /etc/ldap/schema ]; then
    echo "/etc/ldap/schema"
    return 0
  fi
  echo "/etc/ldap/schema"
}

write_slapd_conf() {
  local hash module_path schema_dir
  hash="$(slappasswd -s "${LDAP_ROOT_PW}")"
  module_path="$(detect_module_path)"
  schema_dir="$(detect_schema_dir)"

  cat > "${TMP_CONF}" <<EOF
include         ${schema_dir}/core.schema
include         ${schema_dir}/cosine.schema
include         ${schema_dir}/inetorgperson.schema
include         ${schema_dir}/nis.schema

modulepath      ${module_path}
moduleload      back_mdb
moduleload      memberof
moduleload      refint

pidfile         /run/slapd/slapd.pid
argsfile        /run/slapd/slapd.args

# --- cn=config database ---
database        config
access to *
  by dn.exact="gidNumber=0+uidNumber=0,cn=peercred,cn=external,cn=auth" manage
  by dn.exact="${LDAP_ROOT_DN}" manage
  by * none

# --- main data database ---
database        mdb
maxsize         1073741824
suffix          "${LDAP_SUFFIX}"
rootdn          "${LDAP_ROOT_DN}"
rootpw          ${hash}
directory       "${DB_DIR}"

# Allow binds for normal users (needed for Keycloak / simple bind)
access to attrs=userPassword
  by dn.exact="${LDAP_ROOT_DN}" manage
  by self write
  by anonymous auth
  by * none

# Generic access (tighten later if needed)
access to *
  by dn.exact="${LDAP_ROOT_DN}" manage
  by * read
EOF
}

bootstrap_cn_config_via_slaptest() {
  rm -rf "${SLAPD_D_DIR:?}/"*
  mkdir -p "${SLAPD_D_DIR}" /run/slapd "${DB_DIR}"

  # important: make sure openldap can read/write everything afterwards
  chown -R openldap:openldap /run/slapd "${DB_DIR}" "${SLAPD_D_DIR}"

  write_slapd_conf

  log "bootstrap slapd.d via slaptest for suffix ${LDAP_SUFFIX}"
  slaptest -f "${TMP_CONF}" -F "${SLAPD_D_DIR}" >/dev/null

  # slaptest creates root-owned files → fix
  chown -R openldap:openldap "${SLAPD_D_DIR}"

  if ! has_cn_config; then
    log "slaptest did not generate cn=config; listing:"
    ls -la "${SLAPD_D_DIR}" || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
    fatal "cn=config missing after slaptest"
  fi

  log "cn=config created successfully"
}

init_mdb_files_if_needed() {
  if has_mdb_files; then
    log "data.mdb already exists; skipping MDB init"
    return 0
  fi

  log "initializing MDB files via slapadd -n 1 (creates data.mdb)"
  mkdir -p "${DB_DIR}"
  chown -R openldap:openldap "${DB_DIR}"

  local dc
  dc="$(echo "${LDAP_SUFFIX}" | awk -F'[=,]' '{print $2}' | head -n1)"
  dc="${dc:-infinito}"

  cat <<EOF | slapadd -F "${SLAPD_D_DIR}" -n 1
dn: ${LDAP_SUFFIX}
objectClass: top
objectClass: dcObject
objectClass: organization
o: ${dc}
dc: ${dc}
EOF

  # After slapadd, ensure permissions are correct (locks are sensitive)
  chown -R openldap:openldap "${DB_DIR}"
  chmod 700 "${DB_DIR}" || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error

  if ! has_mdb_files; then
    fatal "MDB files were not created under ${DB_DIR}"
  fi

  log "MDB files initialized"
}

log "starting entrypoint (suffix=${LDAP_SUFFIX}, rootdn=${LDAP_ROOT_DN})"

# Always ensure runtime dirs exist and are writable
mkdir -p /run/slapd "${DB_DIR}" "${SLAPD_D_DIR}"
chown -R openldap:openldap /run/slapd "${DB_DIR}" "${SLAPD_D_DIR}"

if bootstrap_needed; then
  bootstrap_cn_config_via_slaptest
else
  if has_cn_config; then
    log "slapd.d already present; cn=config found"
  else
    log "slapd.d present but cn=config missing -> rebuilding"
    bootstrap_cn_config_via_slaptest
  fi
fi

init_mdb_files_if_needed

# Final permission sweep (this is often the real fix)
chown -R openldap:openldap /run/slapd "${DB_DIR}" "${SLAPD_D_DIR}"
chmod 700 "${DB_DIR}" || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error

log "starting slapd (foreground; drop privileges to openldap)"
exec /usr/sbin/slapd \
  -F "${SLAPD_D_DIR}" \
  -d "${LDAP_LOG_LEVEL}" \
  -h "ldap:/// ldapi:///" \
  -u openldap -g openldap
