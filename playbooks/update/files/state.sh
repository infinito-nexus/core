#!/usr/bin/env bash
# Args:
#   $1  backup directory of the current layout
#   $2  nginx configuration directory of the current layout
#   $3  Let's Encrypt live directory
# Output: one tab-separated record per line, the record kind first.
set -uo pipefail

BACKUP_DIR="${1:?backup directory required}"
NGINX_DIR="${2:?nginx configuration directory required}"
LIVE_DIR="${3:?letsencrypt live directory required}"
LEGACY_NGINX_DIR="/etc/nginx/conf.d"
LEGACY_BACKUP_DIR="/Backups"
export SYSTEMD_COLORS=0

printf 'now\t%s\n' "$(date +%s)"

volume_data=()
while IFS=$'\t' read -r name mountpoint; do
	data="$(readlink -f "$mountpoint")"
	volume_data+=("$data")
	printf 'volume\t%s\t%s\n' "$name" "$data"
done < <(docker volume ls -q 2>/dev/null | xargs -r docker volume inspect --format '{{.Name}}{{"\t"}}{{.Mountpoint}}' 2>/dev/null)

# shellcheck disable=SC2016
docker ps -aq 2>/dev/null | xargs -r docker inspect --type container --format \
	'container{{"\t"}}{{.Name}}{{"\t"}}{{.Config.Image}}{{"\t"}}{{.State.Status}}{{"\t"}}{{index .Config.Labels "com.docker.compose.project"}}{{$n := .Name}}{{range $p, $bs := .HostConfig.PortBindings}}{{range $bs}}{{"\n"}}binding{{"\t"}}{{$n}}{{"\t"}}{{.HostIp}}{{"\t"}}{{.HostPort}}{{"\t"}}{{$p}}{{end}}{{end}}' 2>/dev/null

declare -A container_names=()
while IFS=$'\t' read -r id name; do
	container_names[$id]="$name"
done < <(docker ps --no-trunc --format '{{.ID}}{{"\t"}}{{.Names}}' 2>/dev/null)
while IFS= read -r line; do
	pid="$(grep -oE 'pid=[0-9]+' <<<"$line" | head -1 | cut -d= -f2)"
	id=""
	[[ -z "$pid" ]] || id="$(grep -oE '[0-9a-f]{64}' "/proc/$pid/cgroup" 2>/dev/null | head -1)"
	holder=""
	[[ -z "$id" ]] || holder="${container_names[$id]:-}"
	printf 'listen\t%s\t%s\n' "$line" "$holder"
done < <(ss -H -ltnup 2>/dev/null)

docker network ls -q 2>/dev/null | xargs -r docker network inspect --format \
	'network{{"\t"}}{{.Name}}{{range .IPAM.Config}}{{"\t"}}{{.Subnet}}{{end}}' 2>/dev/null

if ((${#volume_data[@]})); then
	while IFS= read -r file; do
		printf 'dataversion\t%s\t%s\n' "$file" "$(tr -d '\0' <"$file" | head -1)"
	done < <(find -L "${volume_data[@]}" -maxdepth 3 \( -name PG_VERSION -o -name mysql_upgrade_info \) -not -path '*/base/*' 2>/dev/null)
fi
for data in "${volume_data[@]}"; do
	[[ -f "$data/version.php" ]] || continue
	printf 'dataversion\t%s\t%s\n' "$data/version.php" "$(grep -m1 -oE "OC_VersionString = '[^']+'" "$data/version.php" | cut -d"'" -f2)"
done

while IFS=$'\t' read -r name image; do
	[[ "$image" == *openresty* ]] || continue
	output="$(docker exec "$name" openresty -t 2>&1)"
	rc=$?
	printf 'webtest\t%s\t%s\t%s\n' "$name" "$rc" "$(tail -1 <<<"$output")"
done < <(docker ps --filter status=running --format '{{.Names}}{{"\t"}}{{.Image}}' 2>/dev/null)

for dir in "$NGINX_DIR" "$LEGACY_NGINX_DIR"; do
	[[ -d "$dir" ]] || continue
	grep -rHoE '^\s*server_name\s+[^;]+' "$dir" 2>/dev/null | sed -E 's/:\s*server_name\s+/\t/; s/^/servername\t/'
done | sort -u

for cert in "${LIVE_DIR%/}"/*/cert.pem; do
	[[ -f "$cert" ]] || continue
	end="$(openssl x509 -in "$cert" -noout -enddate 2>/dev/null | cut -d= -f2)"
	sans="$(openssl x509 -in "$cert" -noout -ext subjectAltName 2>/dev/null | grep -oE 'DNS:[^,[:space:]]+' | cut -d: -f2 | paste -sd,)"
	printf 'cert\t%s\t%s\t%s\n' "$(basename "$(dirname "$cert")")" "$(date -d "$end" +%s 2>/dev/null)" "$sans"
done

systemctl --failed --no-legend --plain --no-pager 2>/dev/null | awk '{print "failedunit\t" $1}'

declare -A seen_backup_bases=()
for base in "$BACKUP_DIR" "$LEGACY_BACKUP_DIR"; do
	[[ -d "$base" ]] || continue
	real="$(readlink -f "$base")"
	[[ -z "${seen_backup_bases[$real]:-}" ]] || continue
	seen_backup_bases[$real]=1
	while IFS= read -r repo; do
		printf 'backup\t%s\t%s\n' "$repo" "$(find "$repo" -mindepth 1 -maxdepth 1 -printf '%T@\t%f\n' | sort -n | tail -1)"
	done < <(find -L "$base" -mindepth 2 -maxdepth 2 -type d | sort)
done

df -P -x tmpfs -x devtmpfs -x overlay -x squashfs 2>/dev/null | awk 'NR > 1 {print "disk\t" $6 "\t" $5}'
