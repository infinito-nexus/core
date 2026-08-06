#!/bin/bash
#
# Report anonymous volumes that are neither whitelisted nor a bootstrap volume,
# then check every NFS-backed volume for reachability.
#
# Both the container lookup and the mount-path lookup go through the helpers
# below, so the bootstrap check and the report can never disagree about which
# containers hold a volume or where they mount it. The lookup spans stopped
# containers: a reaped container keeps its anonymous bootstrap volume attached,
# and skipping it would report that volume as an anomaly.
#
# Param: $1 space-separated list of whitelisted volume IDs

BOOTSTRAP_MOUNT_PATH="/var/www/bootstrap"

status=0

# Param: $1 volume name
containers_using_volume() {
    container ps -aq --filter volume="$1"
}

# Param: $1 volume name
# Param: $2 container id
volume_mount_path() {
    container inspect --type container --format "{{ range .Mounts }}{{ if eq .Name \"$1\" }}{{ .Destination }}{{ end }}{{ end }}" "$2"
}

# Param: $1 volume name
# Param: $2 space-separated container ids
is_bootstrap_volume() {
    local container_id
    for container_id in $2; do
        if [ "$(volume_mount_path "$1" "$container_id")" == "$BOOTSTRAP_MOUNT_PATH" ]; then
            return 0
        fi
    done
    return 1
}

whitelist="${1:-}"
whitelisted_volumes=()
if [ -n "$whitelist" ]; then
    IFS=' ' read -r -a whitelisted_volumes <<< "$whitelist"
fi

anonymous_volumes=$(container volume ls --format "{{.Name}}" | grep -E '^[a-f0-9]{64}$')

if [ -z "$anonymous_volumes" ]; then
    echo "No anonymous volumes found."
    exit
fi

echo "Anonymous volumes found:"

for volume in $anonymous_volumes; do
    if printf '%s\n' "${whitelisted_volumes[@]}" | grep -q "^$volume$"; then
        echo "Volume $volume is whitelisted and will be skipped."
        continue
    fi

    container_ids=$(containers_using_volume "$volume")

    if is_bootstrap_volume "$volume" "$container_ids"; then
        echo "Volume $volume is a bootstrap volume and will be skipped."
        continue
    fi

    ((status++))

    if [ -z "$container_ids" ]; then
        echo "Volume $volume is not used by any container."
        continue
    fi

    for container_id in $container_ids; do
        container_name=$(container inspect --type container --format '{{ .Name }}' "$container_id" | sed 's#^/##')
        mount_path=$(volume_mount_path "$volume" "$container_id")

        if [ -n "$mount_path" ]; then
            echo "Volume $volume is used by container $container_name at mount path $mount_path"
        else
            echo "Volume $volume is used by container $container_name, but mount path could not be determined."
        fi
    done
done

nfs_volumes=$(container volume ls --filter driver=local --format '{{.Name}}' \
    | while read -r vol; do
        opts=$(container volume inspect "$vol" --format '{{.Options.type}}' 2>/dev/null)
        if [ "$opts" = "nfs" ]; then
            echo "$vol"
        fi
    done)

if [ -n "$nfs_volumes" ]; then
    echo
    echo "============================================================"
    echo "🔍 NFS-backed volumes — reachability check"
    echo "============================================================"
    for vol in $nfs_volumes; do
        device=$(container volume inspect "$vol" --format '{{.Options.device}}' 2>/dev/null)
        addr_opt=$(container volume inspect "$vol" --format '{{.Options.o}}' 2>/dev/null)
        server=$(echo "$addr_opt" | sed -n 's/.*addr=\([^,]*\).*/\1/p')
        export_path="${device#:}"

        if [ -z "$server" ] || [ -z "$export_path" ]; then
            echo "❓ Volume $vol: cannot parse server/export from driver_opts"
            ((status++))
            continue
        fi

        if showmount -e "$server" >/dev/null 2>&1; then
            echo "✅ Volume $vol: server $server reachable for export $export_path"
        else
            echo "❌ Volume $vol: server $server NOT reachable (export $export_path)"
            ((status++))
        fi
    done
fi

exit $status
