#!/usr/bin/env bash
# Param: PGROOT  mount point of the data volume inside the container
# Param: SOURCE  directory of the old cluster relative to PGROOT, empty for PGROOT itself
# Param: MAJORS  space-separated majors from the old cluster's up to the target's
set -euo pipefail

: "${PGROOT:?PGROOT must name the volume mount}"
: "${SOURCE?SOURCE must be set, empty for the volume root}"
: "${MAJORS:?MAJORS must list the majors from old to target}"

log() {
	echo "[pg-upgrade] $*"
}

die() {
	echo "[pg-upgrade] ERROR: $*" >&2
	exit 1
}

as_postgres() {
	gosu postgres "$@"
}

show_failure() {
	local new_dir="$1"
	local file
	while IFS= read -r file; do
		echo "== ${file}" >&2
		cat "${file}" >&2
	done < <(find "${new_dir}/pg_upgrade_output.d" -type f -name '*.txt' 2>/dev/null)
	while IFS= read -r file; do
		echo "== tail ${file}" >&2
		tail -n 40 "${file}" >&2
	done < <(find "${new_dir}/pg_upgrade_output.d" -type f \( -name 'pg_upgrade_server.log' -o -name 'pg_upgrade_internal.log' \) 2>/dev/null)
}

probe_old_cluster() {
	local bin="$1" dir="$2" sock="$3"
	local q=("${bin}/psql" -h "${sock}" -U postgres -d template1 -XAtc)

	as_postgres "${bin}/pg_ctl" -D "${dir}" -w -t 3600 -l "${sock}/probe.log" \
		-o "-c listen_addresses='' -c unix_socket_directories='${sock}'" start >/dev/null ||
		{
			tail -n 40 "${sock}/probe.log" >&2
			die "PostgreSQL could not start on ${dir}"
		}

	local version superuser encoding collate ctype provider="c" locale=""
	version="$(as_postgres "${q[@]}" 'show server_version_num')"
	superuser="$(as_postgres "${q[@]}" 'select rolname from pg_authid where oid = 10')"
	encoding="$(as_postgres "${q[@]}" "select pg_encoding_to_char(encoding) from pg_database where datname = 'template0'")"
	collate="$(as_postgres "${q[@]}" "select datcollate from pg_database where datname = 'template0'")"
	ctype="$(as_postgres "${q[@]}" "select datctype from pg_database where datname = 'template0'")"
	if ((version >= 150000)); then
		provider="$(as_postgres "${q[@]}" "select datlocprovider from pg_database where datname = 'template0'")"
	fi
	if ((version >= 170000)); then
		locale="$(as_postgres "${q[@]}" "select coalesce(datlocale, '') from pg_database where datname = 'template0'")"
	elif ((version >= 150000)); then
		locale="$(as_postgres "${q[@]}" "select coalesce(daticulocale, '') from pg_database where datname = 'template0'")"
	fi

	as_postgres "${bin}/pg_ctl" -D "${dir}" -w -t 3600 -m fast stop >/dev/null

	OLD_SUPERUSER="${superuser}"
	INITDB_ARGS=(--username="${superuser}" --encoding="${encoding}" --lc-collate="${collate}" --lc-ctype="${ctype}")
	case "${provider}" in
	c) ;;
	i) INITDB_ARGS+=(--locale-provider=icu --icu-locale="${locale}") ;;
	b) INITDB_ARGS+=(--locale-provider=builtin --builtin-locale="${locale}") ;;
	*) die "unknown locale provider '${provider}' in ${dir}" ;;
	esac
	log "${dir}: superuser ${superuser}, encoding ${encoding}, collate ${collate}, ctype ${ctype}, provider ${provider} ${locale}"
}

upgrade_step() {
	local old="$1" new="$2" old_dir="$3"
	local bin_old="/usr/lib/postgresql/${old}/bin"
	local bin_new="/usr/lib/postgresql/${new}/bin"
	local step_dir="${PGROOT}/${new}"
	local new_dir="${step_dir}/docker"
	local work="${new_dir}.upgrading"
	local sock checksum file

	[[ -x "${bin_old}/pg_ctl" ]] || die "the image lacks the PostgreSQL ${old} binaries"
	[[ -x "${bin_new}/pg_upgrade" ]] || die "the image lacks the PostgreSQL ${new} binaries"
	[[ "$(cat "${old_dir}/PG_VERSION")" == "${old}" ]] || die "${old_dir} does not hold PostgreSQL ${old}"
	[[ ! -e "${new_dir}" ]] || die "${new_dir} exists already"

	log "PostgreSQL ${old} -> ${new}: ${old_dir} -> ${new_dir}"
	find "${old_dir}" -xdev \! -user postgres -exec chown postgres:postgres {} +
	mkdir -p "${step_dir}"
	rm -rf "${work}"
	mkdir -m 0700 "${work}"
	chown postgres:postgres "${step_dir}" "${work}"

	sock="$(mktemp -d)"
	chown postgres:postgres "${sock}"
	probe_old_cluster "${bin_old}" "${old_dir}" "${sock}"

	checksum="$(as_postgres "${bin_old}/pg_controldata" "${old_dir}" | sed -n 's/^Data page checksum version: *//p')"
	if [[ "${checksum}" != "0" ]]; then
		INITDB_ARGS+=(--data-checksums)
	elif ((new >= 18)); then
		INITDB_ARGS+=(--no-data-checksums)
	fi
	log "data page checksum version ${checksum}"

	as_postgres "${bin_new}/initdb" -D "${work}" "${INITDB_ARGS[@]}" >/dev/null

	cd "${step_dir}"
	local upgrade=("${bin_new}/pg_upgrade" -b "${bin_old}" -B "${bin_new}" -d "${old_dir}" -D "${work}" -U "${OLD_SUPERUSER}")
	as_postgres "${upgrade[@]}" --check || {
		show_failure "${work}"
		die "pg_upgrade --check from ${old} to ${new} failed"
	}
	as_postgres "${upgrade[@]}" --link || {
		show_failure "${work}"
		die "pg_upgrade --link from ${old} to ${new} failed"
	}
	rm -f "${step_dir}/delete_old_cluster.sh"

	for file in pg_hba.conf pg_ident.conf postgresql.auto.conf; do
		if [[ -f "${old_dir}/${file}" ]]; then
			cp -p "${old_dir}/${file}" "${work}/${file}"
		fi
	done
	mv "${work}" "${new_dir}"
	rm -rf "${sock}"
	log "PostgreSQL ${new} cluster ready in ${new_dir}"
}

read -ra majors <<<"${MAJORS}"
((${#majors[@]} >= 2)) || die "MAJORS needs the old and the target major"

old_dir="${PGROOT%/}${SOURCE:+/${SOURCE}}"
for ((i = 0; i + 1 < ${#majors[@]}; i++)); do
	upgrade_step "${majors[i]}" "${majors[i + 1]}" "${old_dir}"
	old_dir="${PGROOT%/}/${majors[i + 1]}/docker"
done
