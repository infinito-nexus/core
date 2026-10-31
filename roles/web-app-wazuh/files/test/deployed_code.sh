#!/usr/bin/env bash
# shellcheck shell=bash
#
# Deployed code check proof, dev and CI only: resets the throwaway checkout DEPLOYED_CODE_PROOF in place to a local
# origin that pretends to be a GitHub repository, runs the deployed check against a local GitHub API stub, and waits
# for each finding as an alert: a clean, verified commit on main raises nothing; a modified tracked file raises its
# rule and a FIM alert; a commit not on main, an unverified commit and a failing API each raise their own rule.
#
# Env (all required; test.sh passes them):
#   ALERTS                   the manager's alerts.json
#   DEPLOYED_CODE_PROOF      the throwaway checkout, also in DEPLOYED_CODE_CHECKOUTS; empty skips the proof
#   DEPLOYED_CODE_SCRIPT     the deployed check
#   DEPLOYED_CODE_TAG        the journald tag the check logs under
#   DEPLOYED_CODE_MODIFIED_RULE, DEPLOYED_CODE_UNMERGED_RULE, DEPLOYED_CODE_UNVERIFIED_RULE, DEPLOYED_CODE_FAILED_RULE
#                            the Wazuh rule ID each finding raises
#   RETRIES, SLEEP_SECONDS   polling for an alert

set -euo pipefail

: "${DEPLOYED_CODE_PROOF?}"
if [[ -z "${DEPLOYED_CODE_PROOF}" ]]; then
	echo "SKIP: no deployed code proof checkout configured"
	exit 0
fi
: "${ALERTS:?}" "${DEPLOYED_CODE_SCRIPT:?}" "${DEPLOYED_CODE_TAG:?}" "${RETRIES:?}" "${SLEEP_SECONDS:?}"
: "${DEPLOYED_CODE_MODIFIED_RULE:?}" "${DEPLOYED_CODE_UNMERGED_RULE:?}" "${DEPLOYED_CODE_UNVERIFIED_RULE:?}"
: "${DEPLOYED_CODE_FAILED_RULE:?}"

RUN="$(date -u +%Y%m%dT%H%M%S)-$$"
PROOF_URL="https://github.com/proof-org/core.git" # nocheck: repository-declared, url -- a fake origin rewritten to a local bare repository through insteadOf, never fetched from GitHub
ORIGIN="$(dirname "${DEPLOYED_CODE_PROOF}")/origin.git"
WORK="$(mktemp -d)"
FILE="proof-${RUN}.txt"

fail() {
	echo "FAIL: $*" >&2
	exit 1
}

pass() {
	echo "PASS: $*"
}

STUB_CODE='
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

port_file, unverified = sys.argv[1], sys.argv[2]


class Stub(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/fail/"):
            status, payload = 502, {"message": "Server Error"}
        else:
            sha = self.path.rsplit("/", 1)[-1]
            verified = sha != unverified
            status, payload = 200, {"sha": sha, "commit": {"verification": {"verified": verified, "reason": "valid" if verified else "unsigned"}}}
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


server = ThreadingHTTPServer(("127.0.0.1", 0), Stub)
with open(port_file, "w", encoding="utf-8") as handle:
    handle.write(str(server.server_address[1]))
server.serve_forever()
'

cleanup() {
	[[ -f "${WORK}/stub.pid" ]] && kill "$(cat "${WORK}/stub.pid")" 2>/dev/null
	rm -rf "${WORK}"
}
trap cleanup EXIT

g() {
	git -c user.name=proof -c user.email=proof@example.invalid -c commit.gpgsign=false "$@"
}

if [[ -d "${DEPLOYED_CODE_PROOF}/.git" ]] && [[ "$(git -C "${DEPLOYED_CODE_PROOF}" config --get remote.origin.url)" != "${PROOF_URL}" ]]; then
	fail "${DEPLOYED_CODE_PROOF} is not the throwaway proof checkout; refusing to rebuild it"
fi

rm -rf "${ORIGIN}"
g init --quiet --bare --initial-branch=main "${ORIGIN}"
g init --quiet --initial-branch=main "${WORK}/src"
echo "base ${RUN}" >"${WORK}/src/${FILE}"
g -C "${WORK}/src" add "${FILE}"
g -C "${WORK}/src" commit --quiet -m "base"
VERIFIED_SHA="$(g -C "${WORK}/src" rev-parse HEAD)"
echo "second ${RUN}" >>"${WORK}/src/${FILE}"
g -C "${WORK}/src" commit --quiet -am "unsigned on main"
UNVERIFIED_SHA="$(g -C "${WORK}/src" rev-parse HEAD)"
g -C "${WORK}/src" switch --quiet -c feature
echo "feature ${RUN}" >>"${WORK}/src/${FILE}"
g -C "${WORK}/src" commit --quiet -am "feature only"
FEATURE_SHA="$(g -C "${WORK}/src" rev-parse HEAD)"
g -C "${WORK}/src" push --quiet "${ORIGIN}" main feature

# Exception: real-time FIM watches the root that existed when the agent started, so it is reset in place, never re-created.
[[ -d "${DEPLOYED_CODE_PROOF}" ]] || fail "${DEPLOYED_CODE_PROOF} is missing; the agent role creates it before FIM starts"
if [[ ! -d "${DEPLOYED_CODE_PROOF}/.git" ]]; then
	g init --quiet --initial-branch=main "${DEPLOYED_CODE_PROOF}"
	g -C "${DEPLOYED_CODE_PROOF}" remote add origin "${PROOF_URL}"
fi
g -C "${DEPLOYED_CODE_PROOF}" config "url.file://${ORIGIN}.insteadOf" "${PROOF_URL}"
g -C "${DEPLOYED_CODE_PROOF}" fetch --quiet --force --prune origin '+refs/heads/*:refs/remotes/origin/*'
g -C "${DEPLOYED_CODE_PROOF}" checkout --quiet --force --detach origin/main
g -C "${DEPLOYED_CODE_PROOF}" clean --quiet -ffdx

python3 -c "${STUB_CODE}" "${WORK}/port" "${UNVERIFIED_SHA}" &
echo $! >"${WORK}/stub.pid"
for ((attempt = 1; attempt <= RETRIES; attempt++)); do
	[[ -s "${WORK}/port" ]] && break
	sleep 1
done
[[ -s "${WORK}/port" ]] || fail "the GitHub API stub did not start"
STUB="http://127.0.0.1:$(cat "${WORK}/port")"
printf 'stub-token' >"${WORK}/token"

# Exception: syscheckd hashes a file when it handles the inotify event, not when the event fires; restoring the file
# before that loses the alert, so the tampered state stays until FIM reports exactly that content.
wait_fim() {
	local path="${DEPLOYED_CODE_PROOF}/${FILE}"
	python3 - "${ALERTS}" "${path}" "$(sha256sum "${path}" | cut -d' ' -f1)" "$((RETRIES * SLEEP_SECONDS))" <<'PY' ||
import json
import sys
import time

alerts, path, sha, timeout = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
deadline = time.time() + timeout
while time.time() <= deadline:
    with open(alerts, encoding="utf-8", errors="replace") as lines:
        for line in lines:
            if path not in line:
                continue
            try:
                syscheck = json.loads(line).get("syscheck", {})
            except ValueError:
                continue
            if syscheck.get("path") == path and syscheck.get("event") == "modified" and syscheck.get("sha256_after") == sha:
                sys.exit(0)
    time.sleep(5)
sys.exit(1)
PY
		fail "no FIM alert for the modified ${path}"
	pass "FIM reported the modified ${path}"
}

check() {
	local name="$1" commit="$2" api="$3"
	g -C "${DEPLOYED_CODE_PROOF}" checkout --quiet --detach "${commit}"
	if [[ "${name}" == "modified" ]]; then
		echo "tampered ${RUN}" >>"${DEPLOYED_CODE_PROOF}/${FILE}"
	fi
	python3 "${DEPLOYED_CODE_SCRIPT}" --checkout="${DEPLOYED_CODE_PROOF}" --api-url="${api}" --token-file="${WORK}/token" \
		--tag="${DEPLOYED_CODE_TAG}" --timeout=30 >"${WORK}/${name}.out" || fail "the deployed code check exited non-zero for ${name}"
	if [[ "${name}" == "modified" ]]; then
		wait_fim
		g -C "${DEPLOYED_CODE_PROOF}" checkout --quiet -- "${FILE}"
	fi
}

check clean "${VERIFIED_SHA}" "${STUB}"
check modified "${VERIFIED_SHA}" "${STUB}"
check unmerged "${FEATURE_SHA}" "${STUB}"
check unverified "${UNVERIFIED_SHA}" "${STUB}"
check failed "${VERIFIED_SHA}" "${STUB}/fail"
g -C "${DEPLOYED_CODE_PROOF}" checkout --quiet --detach "${VERIFIED_SHA}"

python3 - "${WORK}" "${ALERTS}" "${DEPLOYED_CODE_PROOF}" "$((RETRIES * SLEEP_SECONDS))" \
	"${VERIFIED_SHA}" "${FEATURE_SHA}" "${UNVERIFIED_SHA}" <<'PY' || fail "deployed code check"
import json
import os
import sys
import time

work, alerts, proof, timeout, verified, feature, unverified = sys.argv[1:8]
timeout = int(timeout)
expected = {
    "clean": [],
    "modified": [("modified", verified, os.environ["DEPLOYED_CODE_MODIFIED_RULE"])],
    "unmerged": [("unmerged", feature, os.environ["DEPLOYED_CODE_UNMERGED_RULE"])],
    "unverified": [("unverified", unverified, os.environ["DEPLOYED_CODE_UNVERIFIED_RULE"])],
    "failed": [("error", verified, os.environ["DEPLOYED_CODE_FAILED_RULE"])],
}
wanted = []
for case, kinds in expected.items():
    events = [json.loads(line) for line in open(f"{work}/{case}.out", encoding="utf-8")]
    findings = events[:-1]
    got = sorted((event["dc_kind"], event.get("dc_commit")) for event in findings)
    if got != sorted((kind, commit) for kind, commit, _rule in kinds):
        sys.exit(f"{case}: {findings}")
    if case == "failed" and findings[0].get("dc_check") != "verification":
        sys.exit(f"failed: {findings}")
    print(f"PASS: deployed code check {case}: {[kind for kind, _commit, _rule in kinds] or 'no finding'}")
    wanted += [(rule, event) for (kind, _commit, rule), event in zip(kinds, findings)]


def scan():
    found, stray = [], []
    with open(alerts, encoding="utf-8", errors="replace") as lines:
        for line in lines:
            if proof not in line:
                continue
            try:
                alert = json.loads(line)
            except ValueError:
                continue
            full_log = alert.get("full_log", "")
            if "{" not in full_log:
                continue
            try:
                event = json.loads(full_log[full_log.index("{"):])
            except ValueError:
                continue
            found.append((alert["rule"]["id"], event))
            if event.get("dc_commit") == verified and event.get("dc_kind") not in ("modified", "error"):
                stray.append(event)
    return found, stray


deadline = time.time() + timeout
while True:
    found, stray = scan()
    missing = [item for item in wanted if item not in found]
    if not missing or time.time() > deadline:
        break
    time.sleep(5)
if stray:
    sys.exit(f"the clean, verified commit raised alerts: {stray}")
if missing:
    sys.exit(f"no alert for: {missing}")
for rule, event in wanted:
    print(f"PASS: rule {rule} for {event['dc_kind']} {event['dc_commit'][:12]}")
PY

pass "deployed code check"
