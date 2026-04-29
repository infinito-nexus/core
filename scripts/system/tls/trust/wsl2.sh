#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/meta/env/runtime.sh
source "${SCRIPT_DIR}/../../../meta/env/runtime.sh"
[[ "${IS_WSL2}" == "true" ]] || exit 0

# Source project defaults so INFINITO_CONTAINER auto-derives from
# INFINITO_DISTRO (single SPOT in scripts/meta/env/defaults.sh) — no
# local fallback derivation here.
# shellcheck source=scripts/meta/env/defaults.sh
source "${SCRIPT_DIR}/../../../meta/env/defaults.sh"
CONTAINER="${INFINITO_CONTAINER}"
CA_SRC="/etc/infinito.nexus/ca/root-ca.crt"
CA_NAME="infinito-root-ca.crt"

WIN_USER=""
for _dir in /mnt/c/Users/*/; do
	_name="${_dir%/}"
	_name="${_name##*/}"
	case "${_name}" in
	"All Users" | "Default" | "Default User" | "Public" | "desktop.ini") continue ;;
	esac
	WIN_USER="${_name}"
	break
done
WIN_DOWNLOADS="/mnt/c/Users/${WIN_USER}/Downloads"
WIN_CA_PATH="${WIN_DOWNLOADS}/${CA_NAME}"
WIN_CA_PATH_WIN="C:\\Users\\${WIN_USER}\\Downloads\\${CA_NAME}"
POWERSHELL="/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"

# Ensure WSL interop binfmt handler is registered so Windows .exe files can run
if [[ ! -f /proc/sys/fs/binfmt_misc/WSLInterop ]]; then
	echo ">>> Registering WSL interop binfmt handler"
	printf ':WSLInterop:M::MZ::/init:PF\n' | sudo tee /proc/sys/fs/binfmt_misc/register >/dev/null
fi

echo ">>> Extracting CA from container: ${CONTAINER}"
docker cp "${CONTAINER}:${CA_SRC}" "${WIN_CA_PATH}"
echo ">>> CA copied to Windows: ${WIN_CA_PATH_WIN}"

echo ">>> Importing CA into Windows CurrentUser trust store (no admin required)"
"${POWERSHELL}" -NonInteractive -Command "
\$cert = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2('${WIN_CA_PATH_WIN}')
\$store = New-Object System.Security.Cryptography.X509Certificates.X509Store('Root','CurrentUser')
\$store.Open('ReadWrite')
\$store.Add(\$cert)
\$store.Close()
" >/dev/null
echo ">>> CA trusted in Windows (Chrome/Edge will trust *.infinito.example)"

echo ">>> Discovering domains from nginx config"
DOMAINS=$(docker exec "${CONTAINER}" bash -c \
	"find /etc/nginx/conf.d/servers -name '*.conf' | xargs grep -h 'server_name' 2>/dev/null | grep -v '#' | awk '{print \$2}' | tr -d ';' | sort -u")

echo ">>> Updating Windows hosts file (requires one UAC confirmation)"
WIN_TEMP="/mnt/c/Users/${WIN_USER}/AppData/Local/Temp"
PS1_FILE="${WIN_TEMP}/infinito-hosts-setup.ps1"
PS1_FILE_WIN="C:\\Users\\${WIN_USER}\\AppData\\Local\\Temp\\infinito-hosts-setup.ps1"
HOSTS_FILE='C:\Windows\System32\drivers\etc\hosts'
MARKER='# infinito.example --- managed by infinito-nexus'

# shellcheck disable=SC2016
{
	printf '$hostsFile = "%s"\n' "${HOSTS_FILE}"
	printf '$marker = "%s"\n' "${MARKER}"
	printf '$content = Get-Content $hostsFile -Raw -ErrorAction SilentlyContinue\n'
	printf 'if ($content -notmatch [regex]::Escape($marker)) {\n'
	printf '    $entries = "`r`n%s`r`n"\n' "${MARKER}"
	while IFS= read -r domain; do
		[[ -z "${domain}" ]] && continue
		printf '    $entries += "127.0.0.1 %s`r`n"\n' "${domain}"
	done <<<"${DOMAINS}"
	printf '    Add-Content $hostsFile $entries\n'
	printf '}\n'
} >"${PS1_FILE}"

"${POWERSHELL}" -NonInteractive -Command "Start-Process powershell -Verb RunAs -Wait -ArgumentList '-NonInteractive -File ${PS1_FILE_WIN}'"

echo ">>> Windows hosts file updated"
echo ">>> Done — restart your browser to apply CA trust"
