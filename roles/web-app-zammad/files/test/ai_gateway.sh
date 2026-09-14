#!/usr/bin/env bash
# Can the rails container still reach the AI gateway when the tests run?
#
# The probe runs where the consumer runs rather than in a fresh container on the
# same overlay, because an attachment that a new container gets is not evidence
# that a long-lived one still has it. It asks for the model list, which needs no
# credential: any HTTP status proves the socket carried a request and an answer,
# so REFUSED separates a dead listener from TIMEOUT's black hole, and both
# separate either from a gateway that answers and a consumer that mishandles it.
#
# Env (rendered into test.env from templates/test.env.j2):
#   ZAMMAD_AI_PROBE_ENABLED    whether this round serves the AI path at all
#   ZAMMAD_AI_GATEWAY_URL      the OpenAI-compatible base the role configured
#   ZAMMAD_AI_PROBE_CONTAINER  the rails container to probe from
#   ZAMMAD_AI_PROBE_TIMEOUT    seconds to wait before calling it a black hole
set -euo pipefail

: "${ZAMMAD_AI_PROBE_ENABLED:?}"
: "${ZAMMAD_AI_GATEWAY_URL?}"
: "${ZAMMAD_AI_PROBE_CONTAINER?}"
: "${ZAMMAD_AI_PROBE_TIMEOUT:?}"

if [ "${ZAMMAD_AI_PROBE_ENABLED}" != "true" ]; then
  echo "SKIPPED the AI gateway is not served in this round"
  exit 0
fi

if [ -z "${ZAMMAD_AI_GATEWAY_URL}" ] || [ -z "${ZAMMAD_AI_PROBE_CONTAINER}" ]; then
  echo "FAILED the AI path is enabled but the gateway URL or the rails container is empty" >&2
  exit 1
fi

probe=$(
  cat <<'RUBY'
require "net/http"
require "uri"
uri = URI.parse("#{ENV.fetch('URL')}/models")
timeout = Integer(ENV.fetch("TIMEOUT"))
http = Net::HTTP.new(uri.host, uri.port)
http.use_ssl = uri.scheme == "https"
phase = [timeout / 2, 1].max
http.open_timeout = phase
http.read_timeout = phase
started = Process.clock_gettime(Process::CLOCK_MONOTONIC)
begin
  response = http.request(Net::HTTP::Get.new(uri))
  elapsed = Process.clock_gettime(Process::CLOCK_MONOTONIC) - started
  puts format("ANSWERED %s in %.1fs", response.code, elapsed)
rescue Errno::ECONNREFUSED
  puts "REFUSED nothing is listening"
rescue Net::OpenTimeout, Net::ReadTimeout
  elapsed = Process.clock_gettime(Process::CLOCK_MONOTONIC) - started
  puts format("TIMEOUT no answer within %.0fs", elapsed)
rescue StandardError => e
  puts "ERROR #{e.class}"
end
RUBY
)

# nocheck: container-exec-resolver  address resolved by the caller and passed in
verdict="$(container exec -i \
  -e "URL=${ZAMMAD_AI_GATEWAY_URL}" \
  -e "TIMEOUT=${ZAMMAD_AI_PROBE_TIMEOUT}" \
  "${ZAMMAD_AI_PROBE_CONTAINER}" ruby -e "${probe}")"

echo "${verdict}"

case "${verdict}" in
ANSWERED*) exit 0 ;;
*)
  echo "FAILED the rails container cannot reach the AI gateway, so a slow or failing" >&2
  echo "       assistant request is a connectivity fault and not a model or timeout one" >&2
  exit 1
  ;;
esac
