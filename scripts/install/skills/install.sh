#!/usr/bin/env bash
# shellcheck shell=bash
# Restore agent skills from skills-lock.json for reproducible installs.
# Supports Claude Code, Codex, Gemini CLI, Cursor, Copilot, Windsurf, Cline, and more.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../../.." && pwd)"

log() { printf '%s\n' "$*"; }
warn() { printf '%s\n' "$*" >&2; }

if ! command -v npx &>/dev/null; then
	warn "skills: npx not found — skipping installation."
	warn "Install Node.js to enable skills: https://nodejs.org"
	exit 0
fi

cd "${REPO_ROOT}"
log "skills: restoring from skills-lock.json (.agents/skills)..."
npx --yes skills experimental_install
log "skills: installation into .agents/skills complete."

skills_src="${REPO_ROOT}/.agents/skills"
skills_dst="${REPO_ROOT}/.claude/skills"

if [[ ! -d "${skills_src}" ]]; then
	warn "skills: ${skills_src} not found — skipping .claude/skills mirror."
	exit 0
fi

log "skills: mirroring .agents/skills/ -> .claude/skills/..."
rm -rf "${skills_dst}"
mkdir -p "${skills_dst}"
cp -a "${skills_src}/." "${skills_dst}/"
log "skills: mirror complete. Restart Claude Code to load new skills."
