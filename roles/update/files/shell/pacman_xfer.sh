#!/usr/bin/env bash
# Param: $1 output file (pacman's %o), $2 URL (pacman's %u). Exits 0 only on a complete download, else with curl's exit code. A failed attempt is retried 3 times after its partial bytes are dropped, 2 s apart or as long as the Retry-After seconds of a 429/503 ask (at most 30 s); HTTP 404 and 410 fail at once, because every Arch mirror answers the DatabaseOptional .db.sig probe with 404 and pacman ignores that failure.
set -euo pipefail

output="$1"
url="$2"
offset=0
if [[ -f "${output}" ]]; then
	offset="$(stat -c %s -- "${output}")"
fi

for retries_left in 3 2 1 0; do
	# nocheck: curl-timeout  pacman package downloads are size-unbounded; a --max-time would truncate large transfers
	reply="$(curl -L -C - -f --connect-timeout 5 -w '%{http_code} %header{retry-after}' -o "${output}" "${url}")" && exit 0
	status=$?
	code="${reply%% *}"
	retry_after="${reply#* }"
	if [[ "${code}" == 404 || "${code}" == 410 ]] || ((retries_left == 0)); then
		exit "${status}"
	fi
	if [[ -f "${output}" ]]; then
		truncate -s "${offset}" -- "${output}"
	fi
	delay=2
	if [[ "${code}" == 429 || "${code}" == 503 ]] && [[ "${retry_after}" =~ ^[0-9]{1,9}$ ]]; then
		delay=$((10#${retry_after} < 2 ? 2 : (10#${retry_after} > 30 ? 30 : 10#${retry_after})))
	fi
	sleep "${delay}"
done
