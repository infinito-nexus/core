#!/usr/bin/env bash
# Output: the host's backup subjects, one volume name per line.
# Param BKP_TEST_VOLUMES_NO_BACKUP: comma-separated volume names the role hands
#   baudolo as --volumes-no-backup-required.
# Param BKP_TEST_IMAGES_NO_BACKUP: comma-separated image refs the role hands
#   baudolo as --images-no-backup-required. baudolo skips a volume whose running
#   containers all run one of them, and keeps a volume no container runs on.
set -euo pipefail

: "${BKP_TEST_VOLUMES_NO_BACKUP?}"
: "${BKP_TEST_IMAGES_NO_BACKUP?}"

listed() {
    case ",$2," in
    *",$1,"*) return 0 ;;
    *) return 1 ;;
    esac
}

volumes="$(container volume ls -q)"
while IFS= read -r volume; do
    if [[ -z "${volume}" ]] || listed "${volume}" "${BKP_TEST_VOLUMES_NO_BACKUP}"; then
        continue
    fi
    images="$(container ps -q --filter "volume=${volume}" | xargs -r container inspect --type container --format '{{.Config.Image}}')"
    ignored=0
    if [[ -n "${images}" ]]; then
        ignored=1
        while IFS= read -r image; do
            listed "${image}" "${BKP_TEST_IMAGES_NO_BACKUP}" || ignored=0
        done <<<"${images}"
    fi
    if ((ignored == 0)); then
        printf '%s\n' "${volume}"
    fi
done <<<"${volumes}"
