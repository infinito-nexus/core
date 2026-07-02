#!/bin/sh

docker_ps_grep_unhealthy="$(container ps --filter health=unhealthy --format '{{.Names}}')"
docker_ps_grep_exited="$(container ps --filter status=exited --format '{{.ID}}')"

swarm_state="$(container info --format '{{.Swarm.LocalNodeState}}' 2>/dev/null || echo inactive)"
is_manager="$(container info --format '{{.Swarm.ControlAvailable}}' 2>/dev/null || echo false)"

exitcode=0
summary=""

if [ -n "$docker_ps_grep_unhealthy" ]; then
    echo "❌ Some docker containers are unhealthy:"
    echo "$docker_ps_grep_unhealthy"
    echo

    for container_name in $docker_ps_grep_unhealthy
    do
        echo "------------------------------------------------------------"
        echo "🔍 Last 200 log lines for unhealthy container: $container_name"
        echo "------------------------------------------------------------"
        container logs --tail 200 "$container_name" 2>&1 || echo "⚠️ Failed to fetch logs for $container_name"
        echo

        summary="$summary\n - $container_name (unhealthy)"
    done

    if [ "$exitcode" -lt 1 ]; then
        exitcode=1
    fi
fi

if [ "$swarm_state" != "active" ] && [ -n "$docker_ps_grep_exited" ]; then
    for container_id in $docker_ps_grep_exited
    do
        container_exit_code="$(container inspect "$container_id" --format='{{.State.ExitCode}}')"
        container_name="$(container inspect "$container_id" --format='{{.Name}}')"
        container_name="${container_name#/}"

        if [ "$container_exit_code" -ne "0" ]; then
            echo "❌ Container $container_name exited with code $container_exit_code"
            echo "------------------------------------------------------------"
            echo "🔍 Last 200 log lines for exited container: $container_name"
            echo "------------------------------------------------------------"
            container logs --tail 200 "$container_name" 2>&1 || echo "⚠️ Failed to fetch logs for $container_name"
            echo

            summary="$summary\n - $container_name (exited: $container_exit_code)"

            if [ "$exitcode" -lt 2 ]; then
                exitcode=2
            fi
        fi
    done
fi

if command -v container >/dev/null 2>&1; then
    if [ "$swarm_state" = "active" ] && [ "$is_manager" = "true" ]; then
        swarm_candidates="$(container service ls --format '{{.Name}} {{.Replicas}}' 2>/dev/null \
            | awk '{
                split($2, a, "/");
                if (a[1] != a[2]) {
                    print $1 " " $2;
                }
            }')"
        swarm_problems=""
        while read -r service_name replicas; do
            [ -z "$service_name" ] && continue
            task_states="$(container service ps "$service_name" --format '{{.CurrentState}}' 2>/dev/null)"
            if printf '%s\n' "$task_states" | grep -q '^Complete' \
                && ! printf '%s\n' "$task_states" | grep -qE '^(Running|Ready|Starting|Preparing|Pending|Assigned|Accepted|New|Failed|Rejected|Orphaned)'; then
                continue
            fi
            swarm_problems="${swarm_problems:+$swarm_problems
}$service_name $replicas"
        done <<EOF
$swarm_candidates
EOF
        if [ -n "$swarm_problems" ]; then
            echo "❌ Swarm services not fully converged:"
            echo "$swarm_problems"
            echo
            while read -r service_name replicas; do
                echo "------------------------------------------------------------"
                echo "🔍 Recent tasks for swarm service: $service_name ($replicas)"
                echo "------------------------------------------------------------"
                container service ps --no-trunc "$service_name" 2>&1 | head -20 \
                    || echo "⚠️ Failed to fetch tasks for $service_name"
                summary="$summary\n - $service_name (swarm replicas $replicas)"
            done <<EOF
$swarm_problems
EOF
            if [ "$exitcode" -lt 1 ]; then
                exitcode=1
            fi
        fi
    fi
fi

if [ "$exitcode" -ne "0" ]; then
    echo "============================================================"
    echo "🚨 SUMMARY: Unhealthy / Failed Docker Containers"
    echo "============================================================"
    if [ -n "$summary" ]; then
        printf "%b\n" "$summary"
    else
        echo " - (no details collected)"
    fi
    echo "============================================================"
    exit $exitcode
fi

echo "✅ All docker containers are healthy."
exit 0
