.ONESHELL:
SHELL := /bin/bash
.SHELLFLAGS := -euo pipefail -c

# SPOT: Global environment is defined in scripts/meta/env/load.sh.
ENV_SH ?= $(CURDIR)/scripts/meta/env/load.sh
export ENV_SH

# For non-interactive bash, BASH_ENV is sourced so the env layer applies to *all* Make recipes.
ifneq ("$(wildcard $(ENV_SH))","")
export BASH_ENV := $(ENV_SH)
else
$(error Missing env file: $(ENV_SH))
endif

.DEFAULT_GOAL := help

.PHONY: act-all
# Run all act-based deploy checks.
act-all:
	@bash scripts/tests/deploy/act/all.sh

.PHONY: act-app
# Run the act-based app deploy check.
act-app:
	@bash scripts/tests/deploy/act/app.sh

.PHONY: act-workflow
# Run the act-based workflow deploy check.
act-workflow:
	@bash scripts/tests/deploy/act/workflow.sh

.PHONY: autoformat
# Auto-format all source files (skips tools that are not installed).
autoformat: install-lint
	@bash scripts/lint/wrapper.sh autoformat

.PHONY: bootstrap
# Install dependencies and prepare the project.
bootstrap: install setup

.PHONY: build
# Build the local image.
build: fix-dockerignore
	@IMAGE_TAG="$$(bash scripts/meta/resolve/image/local.sh)" \
		bash scripts/image/build.sh

.PHONY: build-cleanup
# Clean up image artifacts.
build-cleanup:
	@bash scripts/image/cleanup.sh

.PHONY: build-dependency
# Pull the build dependency image.
build-dependency:
	@docker pull ghcr.io/kevinveenbirkenbach/pkgmgr-$${INFINITO_DISTRO}:stable

.PHONY: build-missing
# Build the local image if it is missing.
build-missing:
	@IMAGE_TAG="$$(bash scripts/meta/resolve/image/local.sh)" \
		bash scripts/image/build.sh --missing

.PHONY: build-no-cache
# Build the local image without cache.
build-no-cache: build-dependency
	@IMAGE_TAG="$$(bash scripts/meta/resolve/image/local.sh)" \
		bash scripts/image/build.sh --no-cache

.PHONY: build-no-cache-all
# Build the no-cache image for every distro.
build-no-cache-all:
	@set -euo pipefail; \
	for d in $${INFINITO_DISTROS}; do \
		echo "=== build-no-cache: $$d ==="; \
		INFINITO_DISTRO="$$d" "$(MAKE)" build-no-cache; \
	done

.PHONY: clean
# Remove ignored files from the working tree.
# Note: falls back to sudo for container-owned __pycache__/*.pyc; warns and continues if both fail.
clean:
	@echo "Removing ignored git files"
	@if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then \
		if ! git clean -fdX; then \
			echo "git clean failed (likely container-owned files). Retrying with sudo..."; \
			sudo -n git clean -fdX || { \
				echo "WARNING: sudo cleanup also failed; continuing"; \
				exit 0; \
			}; \
		fi; \
	else \
		echo "WARNING: not inside a git repository -> skipping 'git clean -fdX'"; \
		echo "WARNING: (cleanup continues)"; \
	fi

.PHONY: clean-cache
# Wipe on-disk caches under /var/cache/infinito/core/cache/.
# Note: stops cache containers first; re-run `make compose-up` to recreate them.
clean-cache:
	@bash scripts/system/cache/clean.sh

.PHONY: clean-container-owned
# Remove container-owned generated artefacts (build/, tasks/groups/*.yml).
# Note: these files are created inside the compose container with the in-container UID (typically `nobody`); the host cannot rm them directly.
# Note: the helper auto-starts a stopped infinito container before deleting; safe no-op when the targets do not exist.
clean-container-owned:
	@bash scripts/system/cache/clean_container_owned.sh

.PHONY: clean-pycache-dirs
# Remove tracked directories whose only child is a __pycache__ folder.
# Note: catches orphans left after moving or deleting source files.
clean-pycache-dirs:
	@"$${PYTHON}" -m utils.cleanup.pycache_only_dirs

.PHONY: clean-sudo
# Remove ignored files from the working tree with sudo.
clean-sudo:
	@echo "Removing ignored git files with sudo"
	sudo git clean -fdX;

.PHONY: compose-deploy
# Run the local deploy router.
# Usage: make compose-deploy [mode=...] [apps=...] [purge=...] [type=...] [bundles=...] [disabled=...] [full_cycle=...] [variant=...] [debug=...]
# Example: make compose-deploy mode=reinstall apps=web-app-matomo full_cycle=true
# Note: see scripts/tests/deploy/local/deploy/main.sh for the full routing table.
# Param mode: initialize | reinstall | update (default: initialize)
# Param apps: comma-separated app ids (e.g. web-app-matomo,web-app-keycloak)
# Param purge: true | false (default: false) — purge entities before deploy
# Param type: server | workstation | universal (default: from default.env)
# Param bundles: comma-separated bundle names; overrides apps when set
# Param disabled: comma-separated service names to render as disabled
# Param full_cycle: true | false — when true, also run the async update pass
# Param variant: matrix round index to pin the redeploy to a specific variant
# Param debug: true | false (default: from default.env)
compose-deploy:
	@$(if $(apps),INFINITO_APPS="$(apps)") \
	 $(if $(mode),INFINITO_DEPLOY_MODE="$(mode)") \
	 $(if $(purge),INFINITO_PURGE_ENTITIES="$(purge)") \
	 $(if $(type),INFINITO_DEPLOY_TYPE="$(type)") \
	 $(if $(bundles),INFINITO_BUNDLES="$(bundles)") \
	 $(if $(disabled),INFINITO_SERVICES_DISABLED="$(disabled)") \
	 $(if $(full_cycle),INFINITO_FULL_CYCLE="$(full_cycle)") \
	 $(if $(variant),INFINITO_VARIANT="$(variant)") \
	 $(if $(debug),INFINITO_DEBUG="$(debug)") \
	 bash scripts/tests/deploy/local/deploy/main.sh

.PHONY: compose-down
# Stop the development stack.
compose-down:
	@"$${PYTHON}" -m cli.administration.deploy.development down

.PHONY: compose-entity-purge
# Purge one or more app entities from the container.
compose-entity-purge:
	@bash scripts/tests/deploy/local/purge/entity.sh

.PHONY: compose-exec
# Run a shell or one-off command in the running development container.
# Usage: make compose-exec [cmd="..."]
# Example: make compose-exec cmd="ls /opt/src/infinito"
# Param cmd: shell command to run; when unset, opens an interactive shell.
compose-exec:
	@cmd='$(cmd)' bash scripts/tests/deploy/local/exec/container.sh

.PHONY: compose-inner-run
# Run a one-off `docker run` inside the running container (nested Docker-in-Docker).
# Usage: IMAGE=<ref> [cmd="..."] [INFINITO_RUN_FLAGS="..."] make compose-inner-run
# Example: IMAGE=alpine cmd='env' make compose-inner-run
# Param IMAGE: image reference passed to `docker run` (required, e.g. alpine).
# Param cmd: command to execute inside the sidecar; defaults to the image entrypoint.
# Param INFINITO_RUN_FLAGS: extra flags forwarded verbatim to `docker run`.
compose-inner-run:
	@cmd='$(cmd)' bash scripts/tests/deploy/local/exec/run.sh

.PHONY: compose-inventory-refresh
# Refresh the container inventory without deploying apps.
compose-inventory-refresh:
	@bash scripts/tests/deploy/local/reset/inventory.sh

.PHONY: compose-playwright
# Rerun a role-local Playwright spec against the live running stack (no redeploy).
# Usage: make compose-playwright role=<role> [pw="--grep <pattern>"] [keep=true]
# Example: make compose-playwright role=web-app-dashboard pw="--grep icons" keep=true
compose-playwright:
	@: $${role:?role=<role> required, e.g. role=web-app-dashboard}
	@cmd='$(if $(keep),INFINITO_PLAYWRIGHT_KEEP=$(keep) )bash scripts/tests/e2e/rerun-spec.sh $(role) $(pw)' \
	 bash scripts/tests/deploy/local/exec/container.sh

.PHONY: compose-restart
# Restart the development stack.
compose-restart:
	@"$${PYTHON}" -m cli.administration.deploy.development restart

.PHONY: compose-stop
# Stop the development stack without removing volumes.
compose-stop:
	@"$${PYTHON}" -m cli.administration.deploy.development stop

.PHONY: compose-system-purge
# Purge the broader container-level deploy artifacts.
compose-system-purge: compose-entity-purge
	@bash scripts/tests/deploy/local/purge/inventory.sh
	@bash scripts/tests/deploy/local/purge/web.sh
	@bash scripts/tests/deploy/local/purge/lib.sh

.PHONY: compose-up
# Start the development stack.
compose-up: install
	@"$${PYTHON}" -m cli.administration.deploy.development up

.PHONY: console
# Interactive REPL for the infinito.nexus CLI, running on the host.
# Note: each line is forwarded to `python -m cli`; Ctrl+C only cancels the current input.
# Note: exit with `exit`, `quit`, or Ctrl+D.
console:
	@"$${PYTHON}" -m cli.console

.PHONY: diagnose-disk-usage
# Show disk and Docker resource usage to identify what to clean up.
diagnose-disk-usage:
	@bash scripts/system/meta/disk-usage.sh

.PHONY: diagnose-network
# Run the network-diagnose script inside the infinito container.
# Note: covers DNS, TCP, TLS, and PMTU on both IPv4 and IPv6.
diagnose-network:
	@$(MAKE) compose-exec cmd="python3 -m cli.contributing.network.diagnose"

.PHONY: dotenv
# Regenerate .env (SPOT) from default.env + runtime context.
# Note: runtime context covers distro, cache sizes, secrets, and the like.
dotenv:
	@python3 -m cli.meta.env

.PHONY: dotenv-force
# Force a clean .env regeneration in a stripped environment.
# Note: avoids stale BASH_ENV INFINITO_* values pinning via setdefault.
dotenv-force:
	@rm -f .env
	@env -i HOME="$${HOME}" PATH="$${PATH}" python3 -m cli.meta.env

.PHONY: environment-bootstrap
# Bootstrap the local development environment.
environment-bootstrap: wsl2-systemd-check install-python-dev install-lint security-apparmor-teardown network-dns-setup network-ipv6-disable

.PHONY: environment-teardown
# Tear down the local development environment.
environment-teardown: security-apparmor-restore network-dns-remove network-ipv6-restore

.PHONY: fix-chmod
# Mark all shell scripts under scripts/ as executable.
fix-chmod:
	@find scripts/ -name "*.sh" -exec chmod +x {} \;

.PHONY: fix-dockerignore
# Regenerate .dockerignore from .gitignore.
# Note: .gitignore carries the `.git` entry Docker needs.
# Note: race-safe under parallel `make setup` invocations.
fix-dockerignore:
	@echo "Create .dockerignore"
	cat .gitignore > .dockerignore

.PHONY: help
# Print every Make target with the description from its preceding comment line.
# Usage: make help [target=<name>]
# Example: make help target=compose-playwright
help:
	@bash scripts/make/help.sh $(target)

.PHONY: install
# Install all runtime dependencies.
# Note: incremental via a stamp file (see scripts/install/all.sh).
install:
	@bash scripts/install/all.sh

.PHONY: install-agent
# Install OS-level sandbox dependencies required by the Claude Code sandbox.
# Note: pulls in bubblewrap and socat.
install-agent:
	@bash scripts/install/sandbox.sh

.PHONY: install-ansible
# Install Ansible dependencies.
install-ansible:
	@ANSIBLE_COLLECTIONS_DIR="$(HOME)/.ansible/collections" \
	bash scripts/install/ansible.sh

.PHONY: install-force
# Force a full reinstall.
# Note: drops the install stamp and rebuilds it.
install-force:
	@bash scripts/install/all.sh --force

.PHONY: install-lint
# Install lint dependencies.
# Note: host or docker selected via INFINITO_LINT_RUNNER; incremental via a per-env stamp.
install-lint:
	@bash scripts/install/wrapper.sh

.PHONY: install-lint-force
# Force a full lint reinstall.
# Note: drops the per-env stamp and rebuilds it.
install-lint-force:
	@bash scripts/install/wrapper.sh --force

.PHONY: install-python
# Install Python tooling.
install-python: install-venv
	@bash scripts/install/python.sh

.PHONY: install-python-dev
# Install Python tooling including lint and dev dependencies.
install-python-dev: install-python
	@bash scripts/install/python.sh dev
	@bash scripts/install/pre-commit.sh

.PHONY: install-skills
# Install agent skills from skills-lock.json.
install-skills:
	@bash scripts/install/skills/install.sh

.PHONY: install-system-python
# Install the system Python prerequisites.
install-system-python:
	@bash roles/dev-python/files/install.sh ensure

.PHONY: install-venv
# Install the virtual environment.
install-venv: install-system-python
	@bash scripts/install/venv.sh

.PHONY: lint
# Run all lint checks in parallel.
# Note: each check runs on host or in docker per INFINITO_LINT_RUNNER.
lint: install-lint
	@bash scripts/make/parallel.sh lint-action \
		lint-ansible \
		lint-javascript \
		lint-makefile \
		lint-markdown \
		lint-playwright \
		lint-python \
		lint-shellcheck

.PHONY: lint-action
# Run the GitHub Actions lint checks.
lint-action: install-lint
	@bash scripts/lint/wrapper.sh action

.PHONY: lint-ansible
# Run Ansible lint checks.
# Note: runs ansible's syntax-check plus ansible-lint.
lint-ansible: install-lint setup
	@bash scripts/lint/wrapper.sh ansible

.PHONY: lint-javascript
# Run ESLint over the project's JavaScript files.
# Note: covers Playwright specs and persona helpers.
lint-javascript: install-lint
	@bash scripts/lint/wrapper.sh javascript

.PHONY: lint-makefile
# Run checkmake against the Makefile.
lint-makefile: install-lint
	@bash scripts/lint/wrapper.sh makefile

.PHONY: lint-markdown
# Run Markdown lint checks via markdownlint-cli2.
lint-markdown: install-lint
	@bash scripts/lint/wrapper.sh markdown

.PHONY: lint-playwright
# Verify every role's Playwright spec parses + resolves its helpers.
# Note: stages the spec like test-e2e-playwright does and runs `npx playwright test --list`.
lint-playwright: install-lint
	@bash scripts/lint/wrapper.sh playwright

.PHONY: lint-python
# Run Python lint checks.
lint-python: install-lint
	@bash scripts/lint/wrapper.sh python

.PHONY: lint-shellcheck
# Run shellcheck lint checks.
lint-shellcheck: install-lint
	@bash scripts/lint/wrapper.sh shellcheck

.PHONY: meta-list
# Print the repository role list.
meta-list:
	@echo "Generating the roles list"
	@"$${PYTHON}" -m cli.build.list

.PHONY: meta-mig
# Build the meta graph inputs.
meta-mig: meta-list meta-tree
	@echo "Creating meta data for meta infinity graph"

.PHONY: meta-tree
# Print the repository tree.
meta-tree:
	@echo "Generating Tree"
	@"$${PYTHON}" -m cli.build.tree -D 2

.PHONY: network-dns-remove
# Remove the DNS configuration.
network-dns-remove:
	@bash scripts/system/network/dns/remove.sh

.PHONY: network-dns-setup
# Configure DNS on Linux.
network-dns-setup: wsl2-dns-setup
	@bash scripts/system/network/dns/setup/linux.sh

.PHONY: network-ipv6-disable
# Disable IPv6 for local development.
network-ipv6-disable:
	@sudo bash scripts/system/network/ipv6/disable.sh
	@"$(MAKE)" network-refresh

.PHONY: network-ipv6-restore
# Restore IPv6 settings.
network-ipv6-restore:
	@sudo bash scripts/system/network/ipv6/restore.sh
	@"$(MAKE)" network-refresh

.PHONY: network-refresh
# Refresh the running development stack only when it already exists.
network-refresh:
	@bash scripts/system/network/docker/stack_refresh.sh

.PHONY: network-trust-ca
# Trust the local CA on Linux and WSL2.
network-trust-ca:
	@bash scripts/system/tls/trust/linux.sh
	@bash scripts/system/tls/trust/wsl2.sh

.PHONY: requirements-archive
# Archive fully-checked requirement files via pkgmgr (installs kpmx if missing).
requirements-archive:
	@"$${PYTHON}" -m pip install --quiet --upgrade kpmx
	@"$${PYTHON}" -m pkgmgr archive docs/requirements

.PHONY: security-apparmor-restore
# Restore AppArmor profiles.
security-apparmor-restore:
	@echo "==> AppArmor: restore profiles"
	@if grep -q '^[Yy1]' /sys/module/apparmor/parameters/enabled 2>/dev/null; then \
		sudo bash scripts/system/apparmor/restore.sh; \
	else \
		echo "[apparmor] AppArmor module is not loaded — skipping restore"; \
	fi

.PHONY: security-apparmor-teardown
# Tear down AppArmor for local development.
security-apparmor-teardown:
	@echo "==> AppArmor: full teardown (local dev)"
	@if grep -q '^[Yy1]' /sys/module/apparmor/parameters/enabled 2>/dev/null; then \
		sudo bash scripts/system/apparmor/teardown.sh; \
	else \
		echo "[apparmor] AppArmor module is not loaded — skipping teardown"; \
	fi

.PHONY: setup
# Run the setup step after generating .dockerignore.
setup: fix-dockerignore dotenv
	@bash scripts/setup.sh

.PHONY: setup-clean
# Run setup after cleaning ignored files.
setup-clean: clean setup
	@echo "Full build with cleanup before was executed."

.PHONY: system-purge
# Run the broad low-hardware cleanup routine.
system-purge:
	@bash scripts/system/purge/system.sh

.PHONY: test
# Run the full test pipeline (lint + tests).
# Note: parallel execution with fail-fast.
test: install install-lint
	@bash scripts/make/parallel.sh \
		lint \
		test-external \
		test-integration \
		test-lint \
		test-unit

.PHONY: test-external
# Run the external test suite.
test-external: install
	@INFINITO_TEST_TYPE="external" \
	INFINITO_COMPILE=0 \
	bash scripts/tests/code/wrapper.sh

.PHONY: test-integration
# Run the integration test suite.
test-integration: install
	@INFINITO_TEST_TYPE="integration" \
	INFINITO_COMPILE=0 \
	bash scripts/tests/code/wrapper.sh

.PHONY: test-lint
# Run the lint test suite.
test-lint: install
	@INFINITO_TEST_TYPE="lint" \
	INFINITO_COMPILE=0 \
	bash scripts/tests/code/wrapper.sh

.PHONY: test-signed
# Verify HEAD is signed.
# Note: `git log %G?` returns N for unsigned; gates the pre-push hook against unsigned tips.
test-signed:
	@status="$$(git log -1 --pretty=%G?)"; \
	if [ "$$status" = "N" ]; then \
		echo "❌ HEAD commit is not signed. Use 'git-sign-push' or 'git commit -S'." >&2; \
		exit 1; \
	fi; \
	echo "✅ HEAD commit signature status: $$status"

.PHONY: test-unit
# Run the unit test suite.
test-unit: install
	@INFINITO_TEST_TYPE="unit" \
	INFINITO_COMPILE=0 \
	bash scripts/tests/code/wrapper.sh

.PHONY: update-skills
# Update all agent skills to latest versions and refresh skills-lock.json.
update-skills:
	@bash scripts/install/skills/update.sh

.PHONY: wsl2-dns-setup
# Set up DNS on WSL2.
wsl2-dns-setup:
	@sudo bash scripts/system/network/dns/setup/wsl.sh

.PHONY: wsl2-systemd-check
# Enable systemd on WSL2.
wsl2-systemd-check:
	@bash scripts/system/systemd/enable/wsl2.sh

.PHONY: wsl2-trust-windows
# Trust Windows certificates in WSL2.
wsl2-trust-windows:
	@bash scripts/system/tls/trust/wsl2.sh