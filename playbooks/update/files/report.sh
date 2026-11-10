#!/usr/bin/env bash
# Args:
#   $1  compose base directory of the current layout
#   $2  backup directory of the current layout
set -uo pipefail

COMPOSE_DIR="${1:?compose base directory required}"
BACKUP_DIR="${2:?backup directory required}"
LEGACY_COMPOSE_DIR="/opt/docker"
LEGACY_BACKUP_DIR="/Backups"
export SYSTEMD_COLORS=0

section() { printf '\n===== %s =====\n' "$1"; }
run() { "$@" 2>&1 || printf '[rc=%s] %s\n' "$?" "$*"; }

section "host"
run hostname -f
run date -Is
run uptime
run cat /etc/os-release
run uname -a
run nproc
run free -h
run df -hT -x tmpfs -x devtmpfs -x overlay -x squashfs
run ls -la --time-style=long-iso /opt /opt/scripts /opt/ansible-roles /opt/Repositories

section "infinito version"
run grep -E '^INFINITO_VERSION=' /etc/environment
run command -v pkgmgr infinito
while IFS= read -r dir; do
	[[ -e "$dir/pyproject.toml" || -e "$dir/.git" ]] || continue
	printf -- '--- %s\n' "$dir"
	run grep -m1 -E '^version' "$dir/pyproject.toml"
	run git --no-pager -c safe.directory='*' -C "$dir" log -1 --format='%H %cs %d %s'
done < <(find /root /home /opt /srv /usr/local -maxdepth 5 -type d \( -iname '*infinito*' -o -iname '*cymais*' \) -prune 2>/dev/null)
printf 'newest unit files:\n'
find /etc/systemd/system -maxdepth 1 \( -name '*infinito*' -o -name '*cymais*' \) -printf '%TY-%Tm-%Td %TH:%TM %f\n' 2>/dev/null | sort | tail -10

section "docker"
run docker version --format 'server={{.Server.Version}} client={{.Client.Version}}'
run docker compose version
run docker-compose version
run docker info --format 'driver={{.Driver}} root={{.DockerRootDir}} swarm={{.Swarm.LocalNodeState}} cgroup={{.CgroupVersion}}'

section "compose stacks"
for base in "${COMPOSE_DIR%/}" "$LEGACY_COMPOSE_DIR"; do
	[[ -d "$base" ]] || {
		printf '%s: absent\n' "$base"
		continue
	}
	for stack in "$base"/*/; do
		printf '%s: %s\n' "$stack" "$(find "$stack" -mindepth 1 -maxdepth 1 -printf '%y:%f(%TY-%Tm-%Td)\n' | sort | tr '\n' ' ')"
	done
done

section "containers"
printf 'name\timage\timage_id\tversion_label\tstate\tcreated\tproject\tworking_dir\n  mount: type volume source -> destination\n'
docker ps -aq 2>/dev/null | xargs -r docker inspect --type container --format '{{.Name}}{{"\t"}}{{.Config.Image}}{{"\t"}}{{.Image}}{{"\t"}}{{index .Config.Labels "org.opencontainers.image.version"}}{{"\t"}}{{.State.Status}}{{"\t"}}{{.Created}}{{"\t"}}{{index .Config.Labels "com.docker.compose.project"}}{{"\t"}}{{index .Config.Labels "com.docker.compose.project.working_dir"}}{{range .Mounts}}{{"\n  mount: "}}{{.Type}} {{if .Name}}{{.Name}}{{else}}-{{end}} {{.Source}} -> {{.Destination}}{{if not .RW}} (ro){{end}}{{end}}' 2>&1

section "images"
run docker images --format '{{.Repository}}:{{.Tag}}\t{{.ID}}\t{{.CreatedSince}}\t{{.Size}}'

section "volumes"
printf 'name\tdriver\tcreated\tdata\n'
volume_data=()
while IFS=$'\t' read -r name driver created mountpoint; do
	data="$(readlink -f "$mountpoint")"
	volume_data+=("$data")
	printf '%s\t%s\t%s\t%s\n' "$name" "$driver" "$created" "$data"
done < <(docker volume ls -q 2>/dev/null | xargs -r docker volume inspect --format '{{.Name}}{{"\t"}}{{.Driver}}{{"\t"}}{{.CreatedAt}}{{"\t"}}{{.Mountpoint}}' 2>/dev/null)

section "networks"
run docker network ls --format '{{.Name}}\t{{.Driver}}\t{{.Scope}}'

section "database data versions"
while IFS= read -r file; do
	printf '%s: %s\n' "$file" "$(tr -d '\0' <"$file" | head -1)"
done < <(find -L "${volume_data[@]}" "${COMPOSE_DIR%/}" "$LEGACY_COMPOSE_DIR" -maxdepth 3 \( -name PG_VERSION -o -name mysql_upgrade_info \) -not -path '*/base/*' 2>/dev/null)

section "application data versions"
for data in "${volume_data[@]}"; do
	for file in version.php wp-includes/version.php core/Version.php VERSION; do
		[[ -f "$data/$file" ]] || continue
		# shellcheck disable=SC2016
		printf '%s/%s: %s\n' "$data" "$file" "$(grep -m1 -E 'OC_VersionString|\$wp_version =|const VERSION|\$release|^[0-9]' "$data/$file")"
	done
done

section "systemd"
run systemctl list-unit-files --no-legend --no-pager '*infinito*' '*cymais*'
run systemctl list-timers --all --full --no-pager
run systemctl --failed --full --no-legend --no-pager

section "webserver and certificates"
run systemctl is-active nginx openresty
run ls -1 /etc/nginx/conf.d /etc/nginx/sites-enabled
run ls -1 /etc/letsencrypt/live

section "backups"
for base in "${BACKUP_DIR%/}" "$LEGACY_BACKUP_DIR"; do
	[[ -d "$base" ]] || {
		printf '%s: absent\n' "$base"
		continue
	}
	printf '%s -> %s\n' "$base" "$(readlink -f "$base")"
	while IFS= read -r repo; do
		printf '%s: newest %s\n' "$repo" "$(find "$repo" -mindepth 1 -maxdepth 1 -printf '%f\n' | sort | tail -1)"
	done < <(find -L "$base" -mindepth 2 -maxdepth 2 -type d | sort)
done
