#!/usr/bin/env bash
# shellcheck shell=bash
#
# web-svc-github-webhook role test, dev and CI only (criterion G, webhook part):
#   every watched GitHub event, signed like GitHub signs it, raises its rule through the deployed receiver;
#   unsigned, wrongly signed, replayed, oversized and malformed requests are refused and alerted;
#   a push to a repository's default branch whose commit has no merged pull request raises the direct-push rule,
#   checked through a second, throwaway receiver that asks a local GitHub API stub instead of api.github.com.
#
# Env (all required; the role's test.env carries them):
#   ENTITY                   the receiver's journald tag
#   DEFAULT_BRANCH           the default branch the synthetic payloads give their repository
#   MANAGER_LOGS_VOLUME      the Docker volume holding the Wazuh manager's logs
#   MAX_BYTES                the receiver's body limit
#   RECEIVER_HOST            Host header of the receiver's vhost
#   RECEIVER_IMAGE           image the receiver runs in
#   RECEIVER_PATH            path GitHub posts to
#   RECEIVER_PORT            port the receiver listens on inside its container
#   RECEIVER_SCRIPT          the receiver script on the host
#   RECEIVER_URL             the deployed receiver's local base URL
#   RETRIES, SLEEP_SECONDS   polling for an alert
#   WEBHOOK_SECRET           the deployed receiver's webhook secret

set -euo pipefail

: "${ENTITY:?}" "${DEFAULT_BRANCH:?}" "${MANAGER_LOGS_VOLUME:?}" "${MAX_BYTES:?}" "${RECEIVER_HOST:?}"
: "${RECEIVER_IMAGE:?}" "${RECEIVER_PATH:?}" "${RECEIVER_PORT:?}" "${RECEIVER_SCRIPT:?}" "${RECEIVER_URL:?}"
: "${RETRIES:?}" "${SLEEP_SECONDS:?}" "${WEBHOOK_SECRET:?}"

RUN="$(date -u +%Y%m%dT%H%M%S)-$$"
LABEL="infinito-github-webhook-test=${RUN}"
NETWORK="github-webhook-test-${RUN}"
STUB_SECRET="stub-secret-${RUN}"
ALERTS="$(container volume inspect -f '{{.Mountpoint}}' "${MANAGER_LOGS_VOLUME}")/alerts/alerts.json"
BODY_FILE="$(mktemp)"
MERGED_SHA="1111111111111111111111111111111111111111"
DIRECT_SHA="2222222222222222222222222222222222222222"

STUB_CODE='
import json
from http.server import BaseHTTPRequestHandler, HTTPServer

MERGED = "'"${MERGED_SHA}"'"
BRANCH = "'"${DEFAULT_BRANCH}"'"


class Stub(BaseHTTPRequestHandler):
    def do_GET(self):
        pulls = [{"number": 1, "merged_at": "2026-10-26T00:00:00Z", "base": {"ref": BRANCH}}] if MERGED in self.path else []
        body = json.dumps(pulls).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


HTTPServer(("0.0.0.0", 8080), Stub).serve_forever()
'

cleanup() {
	rm -f "${BODY_FILE}"
	container ps -aq --filter "label=${LABEL}" | xargs -r container rm -f >/dev/null
	container network rm "${NETWORK}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

fail() {
	echo "FAIL: $*" >&2
	exit 1
}

pass() {
	echo "PASS: $*"
}

payload() {
	python3 - "$1" "${DEFAULT_BRANCH}" "$2" <<'PY'
import json
import sys

event, branch, sha = sys.argv[1], sys.argv[2], sys.argv[3]
repo = {"full_name": "infinito-nexus/core", "default_branch": branch}
sender = {"login": "octocat"}
payloads = {
    "ping": {"zen": "Keep it logically awesome.", "repository": repo, "sender": sender},
    "push-forced": {"ref": f"refs/heads/{branch}", "forced": True, "deleted": False, "created": False,
                    "before": "a" * 40, "after": sha, "repository": repo, "sender": sender,
                    "commits": [{"id": sha, "distinct": True, "added": [], "modified": ["README.md"], "removed": []}]},
    "push-deleted": {"ref": f"refs/heads/{branch}", "forced": False, "deleted": True, "created": False,
                     "before": "a" * 40, "after": "0" * 40, "repository": repo, "sender": sender, "commits": []},
    "push-workflow": {"ref": f"refs/heads/{branch}", "forced": False, "deleted": False, "created": False,
                      "before": "a" * 40, "after": sha, "repository": repo, "sender": sender,
                      "commits": [{"id": sha, "distinct": True, "added": [], "removed": [],
                                   "modified": [".github/workflows/call-lint.yml"]}]},
    "branch_protection_rule": {"action": "deleted", "rule": {"name": branch}, "repository": repo, "sender": sender},
    "repository_ruleset": {"action": "edited", "repository_ruleset": {"name": "protect-main", "enforcement": "disabled"},
                           "repository": repo, "sender": sender},
    "member": {"action": "added", "member": {"login": "mallory"}, "changes": {"permission": {"to": "admin"}},
               "repository": repo, "sender": sender},
    "organization": {"action": "member_added", "membership": {"user": {"login": "mallory"}, "role": "admin"},
                     "sender": sender},
    "deploy_key": {"action": "created", "key": {"title": "deploy", "read_only": False}, "repository": repo, "sender": sender},
    "secret_scanning_alert": {"action": "created", "alert": {"number": 3, "secret_type": "github_personal_access_token",
                                                             "html_url": "https://github.com/infinito-nexus/core/security/secret-scanning/3"},
                              "repository": repo, "sender": sender},
    "dependabot_alert": {"action": "created", "alert": {"number": 7, "security_advisory": {"severity": "high"},
                                                        "dependency": {"package": {"name": "requests"}},
                                                        "html_url": "https://github.com/infinito-nexus/core/security/dependabot/7"},
                         "repository": repo, "sender": sender},
}
sys.stdout.write(json.dumps(payloads[event]))
PY
}

sign() {
	python3 -c 'import hashlib, hmac, sys; print("sha256=" + hmac.new(sys.argv[1].encode(), sys.stdin.buffer.read(), hashlib.sha256).hexdigest())' "$1"
}

post() {
	local url="$1" secret="$2" event="$3" delivery="$4" body="$5" signature="${6-}" status
	printf '%s' "${body}" >"${BODY_FILE}"
	if [[ "${signature}" == "" ]]; then
		signature="$(sign "${secret}" <"${BODY_FILE}")"
	fi
	if [[ "${signature}" == "none" ]]; then
		status="$(curl -s --connect-timeout 10 --max-time 30 -o /dev/null -w '%{http_code}' -H "Host: ${RECEIVER_HOST}" -H "X-GitHub-Event: ${event}" \
			-H "X-GitHub-Delivery: ${delivery}" -H 'Content-Type: application/json' --data-binary "@${BODY_FILE}" "${url}")"
	else
		status="$(curl -s --connect-timeout 10 --max-time 30 -o /dev/null -w '%{http_code}' -H "Host: ${RECEIVER_HOST}" -H "X-GitHub-Event: ${event}" \
			-H "X-GitHub-Delivery: ${delivery}" -H "X-Hub-Signature-256: ${signature}" -H 'Content-Type: application/json' \
			--data-binary "@${BODY_FILE}" "${url}")"
	fi
	echo "${status}"
}

expect_status() {
	[[ "$1" == "$2" ]] || fail "$3: HTTP $1, expected $2"
}

wait_alert() {
	local delivery="$1" rule="$2" attempt
	for ((attempt = 1; attempt <= RETRIES; attempt++)); do
		if python3 - "${ALERTS}" "${delivery}" "${rule}" <<'PY'; then
import json
import sys

path, delivery, rule = sys.argv[1:4]
with open(path, encoding="utf-8", errors="replace") as alerts:
    for line in alerts:
        if delivery in line and f'"id":"{rule}"' in line:
            alert = json.loads(line)
            if alert["rule"]["id"] == rule and delivery in alert.get("full_log", ""):
                sys.exit(0)
sys.exit(1)
PY
			pass "rule ${rule} for ${delivery}"
			return 0
		fi
		sleep "${SLEEP_SECONDS}"
	done
	fail "no alert ${rule} for ${delivery}"
}

DEPLOYED="${RECEIVER_URL}${RECEIVER_PATH}"

declare -A RULES=(
	[ping]=101101 [push-forced]=101110 [push-deleted]=101111 [push-workflow]=101112
	[branch_protection_rule]=101120 [repository_ruleset]=101121 [member]=101130 [organization]=101131
	[deploy_key]=101133 [secret_scanning_alert]=101140 [dependabot_alert]=101141
)

for case in "${!RULES[@]}"; do
	event="${case%%-*}"
	delivery="test-${RUN}-${case}"
	expect_status "$(post "${DEPLOYED}" "${WEBHOOK_SECRET}" "${event}" "${delivery}" "$(payload "${case}" "${DIRECT_SHA}")")" 202 "${case}"
done

expect_status "$(post "${DEPLOYED}" "${WEBHOOK_SECRET}" ping "test-${RUN}-ping" "$(payload ping "${DIRECT_SHA}")")" 409 "replay"
expect_status "$(post "${DEPLOYED}" "${WEBHOOK_SECRET}" ping "test-${RUN}-unsigned" "$(payload ping "${DIRECT_SHA}")" none)" 401 "unsigned"
expect_status "$(post "${DEPLOYED}" "${WEBHOOK_SECRET}" ping "test-${RUN}-signature" "$(payload ping "${DIRECT_SHA}")" "sha256=$(printf '0%.0s' {1..64})")" 401 "signature"
expect_status "$(post "${DEPLOYED}" "${WEBHOOK_SECRET}" ping "test-${RUN}-oversized" "$(head -c "$((MAX_BYTES + 1))" /dev/zero | tr '\0' 'x')")" 413 "oversized"
expect_status "$(post "${DEPLOYED}" "${WEBHOOK_SECRET}" ping "test-${RUN}-malformed" "not json")" 400 "malformed"

for case in "${!RULES[@]}"; do
	wait_alert "test-${RUN}-${case}" "${RULES[${case}]}"
done
wait_alert "test-${RUN}-ping" 101161
wait_alert "test-${RUN}-unsigned" 101160
wait_alert "test-${RUN}-signature" 101160
wait_alert "test-${RUN}-oversized" 101162
wait_alert "test-${RUN}-malformed" 101163
wait_alert "test-${RUN}-push-forced" 101114

container network create --label "${LABEL}" "${NETWORK}" >/dev/null
container run --detach --name="github-api-stub-${RUN}" --label="${LABEL}" --network="${NETWORK}" \
	--network-alias=github-api-stub "${RECEIVER_IMAGE}" python3 -c "${STUB_CODE}" >/dev/null
container run --detach --name="github-webhook-test-${RUN}" --label="${LABEL}" --network="${NETWORK}" \
	--log-driver=journald --log-opt="tag=${ENTITY}" --publish="127.0.0.1::${RECEIVER_PORT}" \
	--volume="${RECEIVER_SCRIPT}:/app/receiver.py:ro" \
	--env=WEBHOOK_SECRET="${STUB_SECRET}" --env=WEBHOOK_PORT="${RECEIVER_PORT}" --env=WEBHOOK_PATH="${RECEIVER_PATH}" \
	--env=WEBHOOK_MAX_BYTES="${MAX_BYTES}" --env=WEBHOOK_STATE_DB=/tmp/deliveries.sqlite --env=WEBHOOK_REPLAY_DAYS=1 \
	--env=GITHUB_API_URL=http://github-api-stub:8080 --env=GITHUB_TOKEN=stub-token \
	--env=WEBHOOK_PR_ATTEMPTS=2 --env=WEBHOOK_PR_DELAY=1 --env=PYTHONUNBUFFERED=1 \
	"${RECEIVER_IMAGE}" python3 /app/receiver.py >/dev/null
STUB_URL="http://$(container port "github-webhook-test-${RUN}" "${RECEIVER_PORT}/tcp" | head -1)${RECEIVER_PATH}"
for ((attempt = 1; attempt <= RETRIES; attempt++)); do
	curl -sf --connect-timeout 5 --max-time 10 -o /dev/null "${STUB_URL%"${RECEIVER_PATH}"}/healthz" && break
	sleep 1
done

expect_status "$(post "${STUB_URL}" "${STUB_SECRET}" push "test-${RUN}-direct" "$(payload push-forced "${DIRECT_SHA}")")" 202 "direct push"
expect_status "$(post "${STUB_URL}" "${STUB_SECRET}" push "test-${RUN}-merged" "$(payload push-forced "${MERGED_SHA}")")" 202 "merged push"
wait_alert "test-${RUN}-direct" 101113
if container logs "github-webhook-test-${RUN}" 2>&1 | grep -F "test-${RUN}-merged" | grep -qF '"gh_result": "ok"'; then
	pass "a push whose commit came through a merged pull request is not a direct push"
else
	fail "the merged push was not checked as ok"
fi

echo "PASS: web-svc-github-webhook"
