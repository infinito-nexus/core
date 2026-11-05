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

database        config
access to *
  by dn.exact="gidNumber=0+uidNumber=0,cn=peercred,cn=external,cn=auth" manage
  by dn.exact="${LDAP_ROOT_DN}" manage
  by * none

database        mdb
maxsize         1073741824
suffix          "${LDAP_SUFFIX}"
rootdn          "${LDAP_ROOT_DN}"
rootpw          ${hash}
directory       "${DB_DIR}"

access to attrs=userPassword
  by dn.exact="${LDAP_ROOT_DN}" manage
  by self write
  by anonymous auth
  by * none

access to *
  by dn.exact="${LDAP_ROOT_DN}" manage
  by * read
EOF
}

bootstrap_cn_config_via_slaptest() {
  rm -rf "${SLAPD_D_DIR:?}/"*
  mkdir -p "${SLAPD_D_DIR}" /run/slapd "${DB_DIR}"

  chown -R openldap:openldap /run/slapd "${DB_DIR}" "${SLAPD_D_DIR}"

  write_slapd_conf

  log "bootstrap slapd.d via slaptest for suffix ${LDAP_SUFFIX}"
  slaptest -f "${TMP_CONF}" -F "${SLAPD_D_DIR}" >/dev/null || true # nocheck: shell-or-true -- see c4bbbba93: slap_startup opens the not-yet-seeded DB and exits 1 after writing a complete slapd.d; has_cn_config below catches every conversion that really failed

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

  chown -R openldap:openldap "${DB_DIR}"
  chmod 700 "${DB_DIR}" || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error

  if ! has_mdb_files; then
    fatal "MDB files were not created under ${DB_DIR}"
  fi

  log "MDB files initialized"
}

render_ha_cn_config() {
  local source="/etc/ldap/cn-config.ldif"
  local target="/run/slapd/cn-config.ldif"
  [ -f "${source}" ] || fatal "HA form needs ${source} (the per-instance cn=config)"
  OPENLDAP_UID="$(id -u openldap)" OPENLDAP_GID="$(id -g openldap)" \
  ROOT_PW_HASH="$(slappasswd -s "${LDAP_ROOT_PW}")" \
  python3 - "${source}" "${target}" <<'PY'
import os
import sys

text = open(sys.argv[1], encoding="utf-8").read()
for token in ("ROOT_PW_HASH", "OPENLDAP_UID", "OPENLDAP_GID"):
    text = text.replace(f"@{token}@", os.environ[token])
text = text.replace("@ROOT_PW@", os.environ["LDAP_ROOT_PW"])
fd = os.open(sys.argv[2], os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w", encoding="utf-8") as handle:
    handle.write(text)
PY
  rm -rf "${SLAPD_D_DIR:?}/"*
  log "HA: rebuilding slapd.d from the rendered cn=config (data database read-only)"
  slapadd -n 0 -F "${SLAPD_D_DIR}" -l "${target}"
  rm -f "${target}"
  chown -R openldap:openldap "${SLAPD_D_DIR}"
}

stage_ha_credentials() {
  install -m 0400 -o openldap -g openldap /dev/null /run/slapd/peer-bind-pw
  printf '%s' "${LDAP_ROOT_PW}" > /run/slapd/peer-bind-pw
  install -m 0400 -o openldap -g openldap \
    /run/secrets/elector-etcd-password /run/slapd/elector-etcd-password
}

peer_has_data() {
  local peer url
  for peer in ${ELECTOR_PEERS//,/ }; do
    [ "${peer}" = "${ELECTOR_HOST_ID}" ] && continue
    url="ldap://${ELECTOR_PEER_TEMPLATE//\{host\}/${peer}}"
    if ldapsearch -x -o nettimeout=3 -H "${url}" -D "${LDAP_ROOT_DN}" -y /run/slapd/peer-bind-pw \
        -s base -b "${LDAP_SUFFIX}" dn >/dev/null 2>&1; then
      return 0
    fi
  done
  return 1
}

wait_for_ldapi() {
  local attempt
  for attempt in $(seq 1 60); do
    if ldapsearch -Q -Y EXTERNAL -H ldapi:/// -s base -b cn=config dn >/dev/null 2>&1; then
      return 0
    fi
    log "HA: waiting for ldapi (${attempt}/60)"
    sleep 1
  done
  return 1
}

run_ha() {
  : "${LDAP_PORT:?LDAP_PORT must be set in HA form}"
  : "${ELECTOR_HOST_ID:?ELECTOR_HOST_ID must be set in HA form}"

  mkdir -p /run/slapd "${DB_DIR}" "${SLAPD_D_DIR}"
  chown -R openldap:openldap /run/slapd "${DB_DIR}" "${SLAPD_D_DIR}"

  exec 9>"${DB_DIR}/.instance.lock"
  if ! flock -x -n 9; then
    log "HA: waiting for the previous instance to release ${DB_DIR}"
    flock -x 9
  fi

  render_ha_cn_config
  stage_ha_credentials
  if [ "${OPENLDAP_HA_SEED:-false}" = "true" ]; then
    if ! has_mdb_files && peer_has_data; then
      log "HA: a peer already serves ${LDAP_SUFFIX}; replicating instead of seeding"
    else
      init_mdb_files_if_needed
    fi
  fi
  chown -R openldap:openldap "${DB_DIR}"

  log "HA: starting slapd on ${LDAP_PORT} as openldap (read-only until elected)"
  /usr/sbin/slapd -F "${SLAPD_D_DIR}" -d "${LDAP_LOG_LEVEL}" \
    -h "ldap://:${LDAP_PORT}/ ldapi:///" -u openldap -g openldap &
  local slapd_pid=$!

  wait_for_ldapi || fatal "slapd did not open ldapi"

  log "HA: starting writer elector for ${ELECTOR_HOST_ID}"
  ELECTOR_ETCD_CA_FILE=/etc/ssl/etcd/ca.crt \
  ELECTOR_ENGINE=openldap \
  ELECTOR_LDAP_SUFFIX="${LDAP_SUFFIX}" \
  ELECTOR_LDAP_BIND_DN="${LDAP_ROOT_DN}" \
  ELECTOR_LDAP_BIND_PASSWORD_FILE=/run/slapd/peer-bind-pw \
  ELECTOR_ETCD_PASSWORD_FILE=/run/slapd/elector-etcd-password \
    setpriv --reuid=openldap --regid=openldap --init-groups \
    python3 -m infinito_elector &
  local elector_pid=$!

  set +e
  # shellcheck disable=SC2317,SC2329  # invoked through the TERM/INT trap
  shutdown() {
    log "HA: stopping elector first so it turns read-only and releases the lease"
    kill -TERM "${elector_pid}" 2>/dev/null
    wait "${elector_pid}"
    kill -TERM "${slapd_pid}" 2>/dev/null
    wait "${slapd_pid}"
    exit 143
  }
  trap shutdown TERM INT

  wait -n "${slapd_pid}" "${elector_pid}"
  local status=$?
  log "HA: slapd or the elector exited (${status}); stopping the instance"
  kill -TERM "${elector_pid}" "${slapd_pid}" 2>/dev/null
  wait
  exit $(( status == 0 ? 1 : status ))
}

if [ "${OPENLDAP_HA:-false}" = "true" ]; then
  run_ha
fi

log "starting entrypoint (suffix=${LDAP_SUFFIX}, rootdn=${LDAP_ROOT_DN})"

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

chown -R openldap:openldap /run/slapd "${DB_DIR}" "${SLAPD_D_DIR}"
chmod 700 "${DB_DIR}" || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error

log "starting slapd (foreground; drop privileges to openldap)"
exec /usr/sbin/slapd \
  -F "${SLAPD_D_DIR}" \
  -d "${LDAP_LOG_LEVEL}" \
  -h "ldap:/// ldapi:///" \
  -u openldap -g openldap
