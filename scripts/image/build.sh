#!/usr/bin/env bash
set -euo pipefail

: "${INFINITO_DISTRO:?Environment variable 'INFINITO_DISTRO' must be set (arch|debian|ubuntu|fedora|centos)}"
export INFINITO_DISTRO

_build_script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/meta/env/load.sh
source "${_build_script_dir}/../meta/env/load.sh"

: "${INFINITO_PARENT_IMAGE:?Missing INFINITO_PARENT_IMAGE; source scripts/meta/env/load.sh}"

NO_CACHE=0
MISSING_ONLY=0

TARGET=""
IMAGE_TAG="${IMAGE_TAG:-}" # local image name or base tag (without registry); can be pre-set via env
PUSH=0                     # if 1 -> use buildx and push (requires docker buildx)
PUBLISH=0                  # if 1 -> push with semantic tags (latest/version/stable + aliases)
REGISTRY=""                # e.g. ghcr.io
OWNER=""                   # e.g. github org/user
REPO_PREFIX=""             # image repository name
VERSION=""                 # X.Y.Z (required for --publish)
IS_STABLE="false"          # "true" -> publish stable tags
DEFAULT_DISTRO="debian"

usage() {
	local repo_prefix="${REPO_PREFIX:-${INFINITO_IMAGE_REPOSITORY:-<repo>}}" # nocheck: usage-text-placeholder -- '<repo>' is a literal placeholder rendered into --help, not a runtime default

	local default_tag="${repo_prefix}/${INFINITO_DISTRO}"
	if [[ -n "${TARGET:-}" ]]; then
		default_tag="${default_tag}-${TARGET}"
	fi

	cat <<EOF
Usage: INFINITO_DISTRO=<distro> $0 [options]

Build options:
  --missing             Build only if the image does not already exist (local build only)
  --no-cache            Build with --no-cache
  --target <name>       Override Dockerfile target (advanced; default: full).
  --tag <image>         Override the output image tag (default: ${default_tag})

Publish options:
  --push                Push the built image (uses docker buildx build --push)
  --publish             Publish semantic tags (latest, <version>, optional stable) + default-distro aliases
  --registry <reg>      Registry (e.g. ghcr.io)
  --owner <owner>       Registry namespace (e.g. \${GITHUB_REPOSITORY_OWNER})
  --repo-prefix <name>  Image repository name (default: \$INFINITO_IMAGE_REPOSITORY)
  --version <X.Y.Z>     Version for --publish
  --stable <true|false> Whether to publish :stable tags (default: false)

Notes:
- --publish implies --push and requires --registry, --owner, and --version.
- Local build (no --push) uses "docker build" and creates local images like "<repo>/arch".
- If you set NIX_CONFIG in the environment (e.g. access-tokens), it will be forwarded into the build.
EOF
}

while [[ $# -gt 0 ]]; do
	case "$1" in
	--no-cache)
		NO_CACHE=1
		shift
		;;
	--missing)
		MISSING_ONLY=1
		shift
		;;
	--target)
		TARGET="${2:-}"
		[[ -n "${TARGET}" ]] || {
			echo "ERROR: --target requires a value"
			exit 2
		}
		shift 2
		;;
	--tag)
		IMAGE_TAG="${2:-}"
		[[ -n "${IMAGE_TAG}" ]] || {
			echo "ERROR: --tag requires a value"
			exit 2
		}
		shift 2
		;;
	--push)
		PUSH=1
		shift
		;;
	--publish)
		PUBLISH=1
		PUSH=1
		shift
		;;
	--registry)
		REGISTRY="${2:-}"
		[[ -n "${REGISTRY}" ]] || {
			echo "ERROR: --registry requires a value"
			exit 2
		}
		shift 2
		;;
	--owner)
		OWNER="${2:-}"
		[[ -n "${OWNER}" ]] || {
			echo "ERROR: --owner requires a value"
			exit 2
		}
		shift 2
		;;
	--repo-prefix)
		REPO_PREFIX="${2:-}"
		[[ -n "${REPO_PREFIX}" ]] || {
			echo "ERROR: --repo-prefix requires a value"
			exit 2
		}
		shift 2
		;;
	--version)
		VERSION="${2:-}"
		[[ -n "${VERSION}" ]] || {
			echo "ERROR: --version requires a value"
			exit 2
		}
		shift 2
		;;
	--stable)
		IS_STABLE="${2:-}"
		[[ -n "${IS_STABLE}" ]] || {
			echo "ERROR: --stable requires a value (true|false)"
			exit 2
		}
		shift 2
		;;
	-h | --help)
		usage
		exit 0
		;;
	*)
		echo "ERROR: Unknown argument: $1" >&2
		usage
		exit 2
		;;
	esac
done

if [[ -z "${REPO_PREFIX}" ]]; then
	REPO_PREFIX="${INFINITO_IMAGE_REPOSITORY:-}"
fi

if [[ -z "${REPO_PREFIX}" && -z "${IMAGE_TAG}" ]]; then
	echo "ERROR: Missing REPO_PREFIX or INFINITO_IMAGE_REPOSITORY (or set IMAGE_TAG directly)" >&2
	exit 1
fi
if [[ -n "${REPO_PREFIX}" ]]; then
	REPO_PREFIX="${REPO_PREFIX,,}"
fi

if [[ -n "${OWNER}" || -n "${GITHUB_REPOSITORY_OWNER:-}" || -n "${GITHUB_REPOSITORY:-}" ]]; then
	OWNER="$(OWNER="${OWNER}" GITHUB_REPOSITORY_OWNER="${GITHUB_REPOSITORY_OWNER:-}" GITHUB_REPOSITORY="${GITHUB_REPOSITORY:-}" scripts/meta/resolve/repository/owner.sh)"
fi

if [[ -z "${TARGET}" ]]; then
	TARGET="full"
fi

if [[ -z "${IMAGE_TAG}" ]]; then
	IMAGE_TAG="${REPO_PREFIX}/${INFINITO_DISTRO}"
fi

if [[ "${MISSING_ONLY}" == "1" ]]; then
	if [[ "${PUSH}" == "1" ]]; then
		echo "ERROR: --missing is only supported for local builds (without --push/--publish)" >&2
		exit 2
	fi
	if docker image inspect "${IMAGE_TAG}" >/dev/null 2>&1; then
		echo "[build] Image already exists: ${IMAGE_TAG} (skipping due to --missing)"
		exit 0
	fi
fi

if [[ "${PUBLISH}" == "1" ]]; then
	[[ -n "${REGISTRY}" ]] || {
		echo "ERROR: --publish requires --registry"
		exit 2
	}
	[[ -n "${OWNER}" ]] || {
		echo "ERROR: --publish requires --owner"
		exit 2
	}
	[[ -n "${VERSION}" ]] || {
		echo "ERROR: --publish requires --version"
		exit 2
	}
fi

if [[ "${PUSH}" == "1" && "${PUBLISH}" != "1" ]]; then
	if [[ "${IMAGE_TAG}" != */* ]]; then
		echo "ERROR: --push requires --tag with a fully-qualified name (e.g. ghcr.io/<owner>/<repo>/<image>:tag), or use --publish" >&2
		exit 2
	fi
fi

echo
echo "------------------------------------------------------------"
echo "[build] Building image"
echo "distro               = ${INFINITO_DISTRO}"
echo "target               = ${TARGET}"
echo "INFINITO_PARENT_IMAGE = ${INFINITO_PARENT_IMAGE}"
if [[ "${NO_CACHE}" == "1" ]]; then echo "cache               = disabled"; fi
if [[ "${PUSH}" == "1" ]]; then echo "push                = enabled"; fi
if [[ "${PUBLISH}" == "1" ]]; then
	echo "publish             = enabled"
	echo "registry            = ${REGISTRY}"
	echo "owner               = ${OWNER}"
	echo "version             = ${VERSION}"
	echo "stable              = ${IS_STABLE}"
fi
if [[ -n "${NIX_CONFIG:-}" ]]; then
	echo "NIX_CONFIG           = <set>"
else
	echo "NIX_CONFIG           = <empty>"
fi
echo "------------------------------------------------------------"

: "${INFINITO_SRC_DIR:?INFINITO_SRC_DIR must be set; source scripts/meta/env/load.sh}"
: "${INFINITO_VENV_DIR:?INFINITO_VENV_DIR must be set; source scripts/meta/env/load.sh}"
: "${INFINITO_PACKAGE_INSTALL_SCRIPT:?INFINITO_PACKAGE_INSTALL_SCRIPT must be set; source scripts/meta/env/load.sh}"
: "${INFINITO_PYTHON_INSTALL_SCRIPT:?INFINITO_PYTHON_INSTALL_SCRIPT must be set; source scripts/meta/env/load.sh}"
: "${INFINITO_DOCKER_CLI_INSTALL_SCRIPT:?INFINITO_DOCKER_CLI_INSTALL_SCRIPT must be set; source scripts/meta/env/load.sh}"
build_args=(
	--build-arg "INFINITO_PARENT_IMAGE=${INFINITO_PARENT_IMAGE}"
	--build-arg "INFINITO_SRC_DIR=${INFINITO_SRC_DIR}"
	--build-arg "INFINITO_VENV_DIR=${INFINITO_VENV_DIR}"
	--build-arg "INFINITO_PACKAGE_INSTALL_SCRIPT=${INFINITO_PACKAGE_INSTALL_SCRIPT}"
	--build-arg "INFINITO_PYTHON_INSTALL_SCRIPT=${INFINITO_PYTHON_INSTALL_SCRIPT}"
	--build-arg "INFINITO_DOCKER_CLI_INSTALL_SCRIPT=${INFINITO_DOCKER_CLI_INSTALL_SCRIPT}"
	--build-arg "NIX_CONFIG=${NIX_CONFIG:-}"
)

if [[ "${NO_CACHE}" == "1" ]]; then
	build_args+=(--no-cache)
fi

if [[ -n "${TARGET}" ]]; then
	build_args+=(--target "${TARGET}")
fi

compute_publish_tags() {
	local distro_tag_base="${REGISTRY}/${OWNER}/${REPO_PREFIX}/${INFINITO_DISTRO}"
	local alias_tag_base=""

	if [[ "${INFINITO_DISTRO}" == "${DEFAULT_DISTRO}" ]]; then
		alias_tag_base="${REGISTRY}/${OWNER}/${REPO_PREFIX}"
	fi

	local tags=()
	tags+=("${distro_tag_base}:latest")
	tags+=("${distro_tag_base}:${VERSION}")

	if [[ "${IS_STABLE}" == "true" ]]; then
		tags+=("${distro_tag_base}:stable")
	fi

	if [[ -n "${alias_tag_base}" ]]; then
		tags+=("${alias_tag_base}:latest")
		tags+=("${alias_tag_base}:${VERSION}")
		if [[ "${IS_STABLE}" == "true" ]]; then
			tags+=("${alias_tag_base}:stable")
		fi
	fi

	printf '%s\n' "${tags[@]}"
}

_buildx_bin="${HOME}/.docker/cli-plugins/docker-buildx"
if [[ -f "${_buildx_bin}" ]] && command -v file >/dev/null 2>&1; then
	if ! file "${_buildx_bin}" | grep -qE "ELF|executable"; then
		echo "[build] WARNING: Removing corrupted docker-buildx plugin (not an ELF binary)"
		rm -f "${_buildx_bin}"
	fi
fi

if [[ "${PUSH}" == "1" ]]; then
	bx_args=(docker buildx build --push)

	if [[ "${PUBLISH}" == "1" ]]; then
		while IFS= read -r t; do
			bx_args+=(-t "$t")
		done < <(compute_publish_tags)
	else
		bx_args+=(-t "${IMAGE_TAG}")
	fi

	bx_args+=("${build_args[@]}")
	bx_args+=(.)

	echo "[build] Running: ${bx_args[*]}"
	"${bx_args[@]}"
else
	local_args=(docker build)
	local_args+=("${build_args[@]}")
	local_args+=(-t "${IMAGE_TAG}")
	local_args+=(.)

	echo "[build] Running: ${local_args[*]}"
	"${local_args[@]}"
fi
