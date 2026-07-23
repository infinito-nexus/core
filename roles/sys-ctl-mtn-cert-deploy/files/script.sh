#!/bin/sh
set -eu

# Usage: script.sh <ssl_cert_source_dir> <docker_compose_instance_directory>
if [ "$#" -ne 2 ]; then
  echo "Usage: $0 <ssl_cert_source_dir> <docker_compose_instance_directory>" >&2
  exit 1
fi

ssl_cert_source_dir="$1"
docker_compose_instance_directory="$2"

# Compose wrapper base command (must include quoting as needed)
# Example:
#   compose_cmd="compose --chdir /opt/compose/mailu --project mailu"
: "${compose_cmd:=}"

if [ -z "$compose_cmd" ]; then
  echo "ERROR: compose_cmd is not set. It must point to the compose wrapper base command." >&2
  echo "Example: compose_cmd='compose --chdir <dir> --project <name>'" >&2
  exit 1
fi

# Keep your existing target layout (minimal change)
docker_compose_cert_directory="${docker_compose_instance_directory%/}/volumes/certs"

if [ ! -d "$ssl_cert_source_dir" ]; then
  echo "ERROR: ssl_cert_source_dir does not exist or is not a directory: $ssl_cert_source_dir" >&2
  exit 1
fi

# Ensure the target cert directory exists
if [ ! -d "$docker_compose_cert_directory" ]; then
  echo "Creating certs directory: $docker_compose_cert_directory"
  mkdir -p "$docker_compose_cert_directory"
fi

echo "Copying certificates from: $ssl_cert_source_dir -> $docker_compose_cert_directory"
cp -RvL "${ssl_cert_source_dir}/"* "$docker_compose_cert_directory"

# Mailu optimization: create key.pem/cert.pem from whatever exists
# Prefer LE naming if present
if [ -f "${ssl_cert_source_dir}/privkey.pem" ] && [ -f "${ssl_cert_source_dir}/fullchain.pem" ]; then
  cp -v "${ssl_cert_source_dir}/privkey.pem"   "${docker_compose_cert_directory}/key.pem"
  cp -v "${ssl_cert_source_dir}/fullchain.pem" "${docker_compose_cert_directory}/cert.pem"
elif [ -f "${ssl_cert_source_dir}/key.pem" ] && [ -f "${ssl_cert_source_dir}/cert.pem" ]; then
  cp -v "${ssl_cert_source_dir}/key.pem"  "${docker_compose_cert_directory}/key.pem"
  cp -v "${ssl_cert_source_dir}/cert.pem" "${docker_compose_cert_directory}/cert.pem"
else
  echo "ERROR: Could not determine key/cert mapping for Mailu." >&2
  echo "Looked for: privkey.pem+fullchain.pem OR key.pem+cert.pem in: $ssl_cert_source_dir" >&2
  exit 1
fi

# Set correct reading rights
chmod a+r -v "${docker_compose_cert_directory}/"* || exit 1

# Ensure we can chdir (compose project dir)
cd "$docker_compose_instance_directory" || exit 1

# List services via wrapper to ensure correct -p/-f/--env-file stack is used
# IMPORTANT: use "--" to stop wrapper arg parsing (so compose flags like "--services" are passed through)
services="$(sh -c "$compose_cmd -- ps --services")"

# Restart every service that consumes the deployed certificate material, i.e.
# has the cert directory bind-mounted. The TLS terminator differs per provider
# (Mailu: the nginx front container; Stalwart: the mail server itself), so
# selection MUST go by consumption, not by which binary a container ships —
# a service that keeps running with the old cert serves it until expiry.
restart_services=""

for service in $services; do
  echo "Checking service: $service"

  container_id="$(sh -c "$compose_cmd -- ps -q \"$service\"" | head -n1)"
  if [ -z "$container_id" ]; then
    echo "No running container for service: $service, skipping."
    continue
  fi

  if docker inspect "$container_id" \
      --format '{{range .Mounts}}{{println .Source}}{{end}}' \
      | grep -qx "$docker_compose_cert_directory"; then
    echo "Certificate mount found in service: $service"
    restart_services="$restart_services $service"
  else
    echo "No certificate mount in service: $service, skipping."
  fi
done

if [ -n "$(echo "$restart_services" | tr -d ' ')" ]; then
  echo "Restarting certificate-consuming services to apply new certificates:${restart_services}"
  # shellcheck disable=SC2086
  sh -c "$compose_cmd -- restart $restart_services" || exit 1
else
  echo "No certificate-consuming services found. Nothing to restart."
fi
