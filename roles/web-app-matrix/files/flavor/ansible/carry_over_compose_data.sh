#!/usr/bin/env bash
# Param: MATRIX_COMPOSE_VOLUME       - docker volume the compose flavor mounts into synapse
# Param: MATRIX_COMPOSE_MOUNT        - path synapse mounts that volume at under the compose flavor
# Param: MATRIX_COMPOSE_SIGNING_KEY  - signing_key_path of the compose flavor's homeserver.yaml
# Param: MATRIX_COMPOSE_MEDIA_STORE  - media_store_path of the compose flavor's homeserver.yaml
# Param: MATRIX_MDAD_VOLUME          - docker volume the matrix-mdad runner mounts as MDAD's data root
# Param: MATRIX_MDAD_MOUNT           - path the runner mounts that volume at (MDAD's matrix_base_data_path)
# Param: MATRIX_MDAD_SIGNING_KEY     - signing key MDAD's synapse reads, as a path inside the runner
# Param: MATRIX_MDAD_MEDIA_STORE     - media store MDAD's synapse serves, as a path inside the runner
# Param: MATRIX_SYNAPSE_UID          - uid synapse runs as under MDAD
# Param: MATRIX_SYNAPSE_GID          - gid synapse runs as under MDAD
# Output: one SKIPPED, KEPT or COPIED line per item; COPIED means the MDAD volume changed.
set -euo pipefail

: "${MATRIX_COMPOSE_VOLUME:?}"
: "${MATRIX_COMPOSE_MOUNT:?}"
: "${MATRIX_COMPOSE_SIGNING_KEY:?}"
: "${MATRIX_COMPOSE_MEDIA_STORE:?}"
: "${MATRIX_MDAD_VOLUME:?}"
: "${MATRIX_MDAD_MOUNT:?}"
: "${MATRIX_MDAD_SIGNING_KEY:?}"
: "${MATRIX_MDAD_MEDIA_STORE:?}"
: "${MATRIX_SYNAPSE_UID:?}"
: "${MATRIX_SYNAPSE_GID:?}"

owner="${MATRIX_SYNAPSE_UID}:${MATRIX_SYNAPSE_GID}"

on_volume() {
	case "$3" in
	"$2"/?*) printf '%s/%s\n' "$1" "${3#"$2"/}" ;;
	*)
		echo "FAILED: $3 is not below the mount point $2" >&2
		return 1
		;;
	esac
}

holds_entries() {
	[ -d "$1" ] && [ -n "$(find "$1" -mindepth 1 -maxdepth 1 -print -quit)" ]
}

key_id() {
	head -n 1 -- "$1" | cut -d ' ' -f 1,2 | tr ' ' ':'
}

ensure_parent() {
	local dir
	dir="$(dirname -- "$1")"
	if [ ! -d "$dir" ]; then
		ensure_parent "$dir"
		mkdir -- "$dir"
		chown -- "$owner" "$dir"
		chmod 0750 "$dir"
	fi
}

compose_listed="$(container volume ls -q -f "name=^${MATRIX_COMPOSE_VOLUME}$")"
if [ -z "$compose_listed" ]; then
	echo "SKIPPED: no compose flavor volume ${MATRIX_COMPOSE_VOLUME} on this host"
	exit 0
fi

compose_root="$(container volume inspect --format '{{ .Mountpoint }}' "$MATRIX_COMPOSE_VOLUME")"
source_key="$(on_volume "$compose_root" "$MATRIX_COMPOSE_MOUNT" "$MATRIX_COMPOSE_SIGNING_KEY")"
source_media="$(on_volume "$compose_root" "$MATRIX_COMPOSE_MOUNT" "$MATRIX_COMPOSE_MEDIA_STORE")"

if [ ! -f "$source_key" ] && ! holds_entries "$source_media"; then
	echo "SKIPPED: ${MATRIX_COMPOSE_VOLUME} holds neither a signing key nor media"
	exit 0
fi

mdad_listed="$(container volume ls -q -f "name=^${MATRIX_MDAD_VOLUME}$")"
if [ -z "$mdad_listed" ]; then
	container volume create "$MATRIX_MDAD_VOLUME" >/dev/null
fi

mdad_root="$(container volume inspect --format '{{ .Mountpoint }}' "$MATRIX_MDAD_VOLUME")"
target_key="$(on_volume "$mdad_root" "$MATRIX_MDAD_MOUNT" "$MATRIX_MDAD_SIGNING_KEY")"
target_media="$(on_volume "$mdad_root" "$MATRIX_MDAD_MOUNT" "$MATRIX_MDAD_MEDIA_STORE")"

if [ ! -f "$source_key" ]; then
	echo "SKIPPED: no signing key at ${MATRIX_COMPOSE_SIGNING_KEY} in ${MATRIX_COMPOSE_VOLUME}"
elif [ -e "$target_key" ]; then
	echo "KEPT: ${MATRIX_MDAD_SIGNING_KEY} already holds $(key_id "$target_key"), the compose flavor signed with $(key_id "$source_key")"
else
	ensure_parent "$target_key"
	cp -p -- "$source_key" "${target_key}.carry-over"
	chown -- "$owner" "${target_key}.carry-over"
	mv -- "${target_key}.carry-over" "$target_key"
	echo "COPIED: signing key $(key_id "$target_key") to ${MATRIX_MDAD_SIGNING_KEY}"
fi

if ! holds_entries "$source_media"; then
	echo "SKIPPED: no media at ${MATRIX_COMPOSE_MEDIA_STORE} in ${MATRIX_COMPOSE_VOLUME}"
elif holds_entries "$target_media"; then
	echo "KEPT: ${MATRIX_MDAD_MEDIA_STORE} already holds media"
elif [ -e "$target_media" ] && [ ! -d "$target_media" ]; then
	echo "FAILED: ${MATRIX_MDAD_MEDIA_STORE} exists and is not a directory" >&2
	exit 1
else
	staging="${target_media}.carry-over"
	rm -rf -- "$staging"
	ensure_parent "$target_media"
	cp -a -- "$source_media" "$staging"
	chown -R -- "$owner" "$staging"
	if [ -d "$target_media" ]; then
		rmdir -- "$target_media"
	fi
	mv -- "$staging" "$target_media"
	echo "COPIED: media store to ${MATRIX_MDAD_MEDIA_STORE}"
fi
