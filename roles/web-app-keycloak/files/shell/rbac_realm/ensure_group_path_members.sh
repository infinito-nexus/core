#!/usr/bin/env bash
# Ensure a nested Keycloak realm group path exists and the given users are
# members of its leaf group. Used by the LDAP-disabled RBAC provisioning path
# to materialise /<group_root>/<app>/<role> groups that the LDAP federation
# would otherwise import.
#
# Required env:
#   KC_CONTAINER   keycloak container name
#   KC_REALM       realm name
#   GROUP_PATH     slash-separated path without leading slash, e.g.
#                  roles/web-app-prometheus/administrator
# Optional env:
#   MEMBERS        space-separated usernames to add to the leaf group
set -o pipefail
: "${KC_CONTAINER:?KC_CONTAINER is required}"
: "${KC_REALM:?KC_REALM is required}"
: "${GROUP_PATH:?GROUP_PATH is required}"

kc() { container exec -i "$KC_CONTAINER" /opt/keycloak/bin/kcadm.sh "$@"; }

_uuid_re='[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}'

parent_id=""
IFS='/' read -ra _segments <<<"$GROUP_PATH"
for seg in "${_segments[@]}"; do
	[ -n "$seg" ] || continue

	if [ -z "$parent_id" ]; then
		listing="$(kc get groups -r "$KC_REALM" -q max=500 \
			--fields id,name --format csv --noquotes 2>/dev/null)"
	else
		listing="$(kc get "groups/$parent_id/children" -r "$KC_REALM" -q max=500 \
			--fields id,name --format csv --noquotes 2>/dev/null)"
	fi

	seg_id="$(printf '%s\n' "$listing" \
		| awk -F',' -v n="$seg" '!/^\[/ && !/Cgroup/ && $2==n {print $1; exit}' \
		| tr -d '\r')"

	if [ -z "$seg_id" ]; then
		if [ -z "$parent_id" ]; then
			out="$(kc create groups -r "$KC_REALM" -s "name=$seg" -i 2>/dev/null)"
		else
			out="$(kc create "groups/$parent_id/children" -r "$KC_REALM" \
				-s "name=$seg" -i 2>/dev/null)"
		fi
		seg_id="$(printf '%s\n' "$out" | grep -Eio "$_uuid_re" | head -n1 | tr -d '\r')"
	fi

	if [ -z "$seg_id" ]; then
		echo "[keycloak][rbac] failed to ensure group segment '$seg' in '/$GROUP_PATH'" >&2
		exit 1
	fi
	parent_id="$seg_id"
done

leaf_id="$parent_id"

# shellcheck disable=SC2086 # MEMBERS is an intentional space-separated list.
for username in ${MEMBERS:-}; do
	raw="$(kc get users -r "$KC_REALM" -q username="$username" -q exact=true \
		--fields id --format csv --noquotes 2>/dev/null)"
	uid="$(printf '%s\n' "$raw" | grep -Eio "$_uuid_re" | head -n1 | tr -d '\r')"
	if [ -z "$uid" ]; then
		echo "[keycloak][rbac] member '$username' not found in realm (expected: seeded by 08_users_realm before this runs)" >&2
		exit 1
	fi
	if ! kc update "users/$uid/groups/$leaf_id" -r "$KC_REALM" \
		-s "realm=$KC_REALM" -s "userId=$uid" -s "groupId=$leaf_id" -n >/dev/null; then
		echo "[keycloak][rbac] failed to add member '$username' to /$GROUP_PATH" >&2
		exit 1
	fi
	echo "[keycloak][rbac] member '$username' -> /$GROUP_PATH"
done

echo "[keycloak][rbac] ensured /$GROUP_PATH ($leaf_id)"
