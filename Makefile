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

.PHONY: act-debug
# Param: node=<container_name> cmd='<shell pipeline>'
act-debug:
	@docker exec $(node) bash --noprofile --norc -c "$(cmd)"

.PHONY: act-runner-image
# Build local/act-runner-fixed: the stock act runner image with /var/run removed so a recent Docker engine accepts act's job-setup content copy.
# Usage: ACT_PLATFORM_IMAGE=local/act-runner-fixed:latest make swarm-zombie app=<app>
# Note: see docs/agents/action/iteration/workflow.md.
act-runner-image:
	@bash scripts/tests/deploy/act/build_runner_image.sh

.PHONY: act-workflow
# Run the act-based workflow deploy check.
act-workflow: install-act
	@bash scripts/tests/deploy/act/workflow.sh

.PHONY: alias
# Print the portable agent shortcuts and the operator's terminal aliases.
alias:
	@bash scripts/make/alias.sh

.PHONY: autoformat
# Auto-format all source files (skips tools that are not installed).
autoformat: install-lint
	@bash scripts/lint/wrapper.sh autoformat

.PHONY: autoformat-restage
# Autoformat, then re-stage files it rewrote that were already staged -- only when no unstaged changes were present beforehand.
autoformat-restage:
	@bash scripts/git/autoformat_restage.sh "$(MAKE)" autoformat

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

.PHONY: cheat
# Print the operator prompt cheatsheet from docs/contributing/tools/agents/cheatsheet.md.
cheat:
	@bash scripts/make/cheatsheet.sh

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

.PHONY: clean-stale-nfs
# Recover stale in-namespace NFS mounts from wedged act-swarm nfs-server containers.
# Usage: make clean-stale-nfs [cid=<container-id-or-name>] [mount=/mnt/gtest]
clean-stale-nfs: swarm-clean-stale-nfs

.PHONY: clean-sudo
# Remove ignored files from the working tree with sudo.
clean-sudo:
	@echo "Removing ignored git files with sudo"
	sudo git clean -fdX;

.PHONY: compose-deploy
# Run the local deploy router.
# Usage: make compose-deploy [mode=...] [apps=...] [purge=...] [type=...] [bundles=...] [disable=...] [full_cycle=...] [variant=...] [debug=...]
# Example: make compose-deploy mode=reinstall apps=web-app-matomo full_cycle=true
# Note: see scripts/tests/deploy/local/deploy/main.sh for the full routing table.
# Param mode: initialize | reinstall | update (default: initialize)
# Param apps: comma-separated app ids (e.g. web-app-matomo,web-app-keycloak)
# Param purge: true | false (default: false) — purge entities before deploy
# Param bundles: comma-separated bundle names; overrides apps when set
# Param disable: comma-separated service names to render as disabled
# Param full_cycle: true | false — when true, also run the async update pass
# Param variant: matrix round index to pin the redeploy to a specific variant
# Param debug: true | false (default: from default.env)
compose-deploy:
	@$(if $(debug),INFINITO_DEBUG="$(debug)") \
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

.PHONY: cosmos
# Regenerate the '## Cosmos' mermaid diagram in every role README (or one role).
# Usage: make cosmos [role=<id>]
# Param role: single role id (default: all roles)
cosmos:
	@"$${PYTHON}" -m cli.build.readme $(role) --update-cosmos

.PHONY: diagnose-disk-usage
# Show disk and Docker resource usage to identify what to clean up.
diagnose-disk-usage:
	@bash scripts/system/meta/disk-usage.sh

.PHONY: diagnose-network
# Run the network-diagnose script inside the infinito container.
# Note: covers DNS, TCP, TLS, and PMTU on both IPv4 and IPv6.
diagnose-network:
	@$(MAKE) compose-exec cmd="python3 -m cli.contributing.network.diagnose"

.PHONY: docs
# Regenerate generated documentation: role Cosmos diagrams, Quick Setup blocks, and the root-README roles index.
docs:
	@"$(MAKE)" cosmos
	@"$(MAKE)" readme-generate quick_setup=true
	@"$(MAKE)" readme-index

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

.PHONY: install-act
# Install act (nektos/act) if missing; provisions the act-based make targets.
install-act:
	@bash scripts/install/act.sh

.PHONY: install-act-update
# Force act (nektos/act) to its latest release.
install-act-update:
	@bash scripts/install/act.sh update

.PHONY: install-agent
# Install OS-level sandbox dependencies required by the Claude Code sandbox.
# Note: pulls in bubblewrap and socat.
install-agent:
	@bash scripts/install/sandbox.sh

.PHONY: install-alias
# Install the terminal aliases from INFINITO_ALIAS_REPOSITORY into the user's shell config.
install-alias:
	@bash scripts/install/alias.sh

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
# Install the agent skills from INFINITO_SKILLS_REPOSITORY into this project.
install-skills:
	@bash scripts/install/skills.sh

.PHONY: install-system-python
# Install the system Python prerequisites.
install-system-python:
	@bash "$${INFINITO_PYTHON_INSTALL_SCRIPT:?}" ensure

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
		lint-dockerfile \
		lint-javascript \
		lint-makefile \
		lint-markdown \
		lint-mermaid \
		lint-packages \
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

.PHONY: lint-dockerfile
# Run hadolint over the root Dockerfile.
lint-dockerfile: install-lint
	@bash scripts/lint/wrapper.sh dockerfile

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

.PHONY: lint-mermaid
# Render every Markdown mermaid diagram via mmdc; fails on any diagram GitHub cannot render.
lint-mermaid: install-lint
	@bash scripts/lint/wrapper.sh mermaid

.PHONY: lint-packages
# Validate distro packaging metadata (debian changelog, fedora spec, arch PKGBUILD).
# Note: provisions the native parsers explicitly, then validates; absent tools are skipped.
lint-packages: install-lint
	@bash scripts/install/wrapper.sh packages
	@bash scripts/lint/wrapper.sh packages

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

.PHONY: onboard
# Set up a developer workstation end to end: dependencies, project setup, agent skills, terminal aliases, host network/security prep, and the dev extras inside the running dev container.
onboard: bootstrap install-skills install-alias environment-bootstrap
	@"$(MAKE)" compose-up
	@"$(MAKE)" compose-exec cmd="bash scripts/install/dev-extras.sh"

.PHONY: quality
# Regenerate generated docs, autoformat, then run the full test suite (pre-commit gate).
quality:
	@"$(MAKE)" docs
	@"$(MAKE)" autoformat
	@"$(MAKE)" test

.PHONY: quality-high
# Full gate: quality (autoformat + test) followed by every lint check.
quality-high: quality lint

.PHONY: readme-check
# Verify every role README matches the schema template (writes nothing; fails if any would change).
readme-check:
	@"$${PYTHON}" -m cli.build.readme --check

.PHONY: readme-generate
# Generate/complete role README.md files from templates/roles/README.md.j2.tmpl.
# Usage: make readme-generate [role=<id>] [override=true] [cosmos=true] [quick_setup=true]
# Param role: single role id (default: all roles)
# Param override: true regenerates managed sections even when present
# Param cosmos: true regenerates only the Cosmos diagram
# Param quick_setup: true regenerates only the Quick Setup section
readme-generate:
	@"$${PYTHON}" -m cli.build.readme $(role) $(if $(filter true,$(override)),--override) $(if $(filter true,$(cosmos)),--update-cosmos) $(if $(filter true,$(quick_setup)),--update-quick-setup)

.PHONY: readme-index
# Regenerate the invokable-role overview table in the root README.md.
# Param check: true verifies only and fails when the table is outdated
readme-index:
	@"$${PYTHON}" -m cli.build.readme.overview $(if $(filter true,$(check)),--check)

.PHONY: requirements-archive
# Archive fully-checked requirement files via pkgmgr (installs kpmx if missing).
requirements-archive:
	@"$${PYTHON}" -m pip install --quiet --upgrade kpmx
	@"$${PYTHON}" -m pkgmgr archive docs/requirements

.PHONY: roundtrip
# Validate one or more roles through every deploy mode in order (compose, then swarm), stopping at the first failure.
# Param apps: space-separated role ids; default = one role per base cluster, most-complex first (complexity --unique).
# Param modes: optional mode sequence (default "compose swarm"; append k8s once it exists).
# Param keep: true keeps each validated swarm cluster instead of releasing it.
roundtrip:
	@apps='$(apps)' modes='$(modes)' keep='$(keep)' bash scripts/tests/deploy/roundtrip.sh

.PHONY: runner-ci-deploy
# Provision self-hosted CI runner instances on a remote host.
# Usage: make runner-ci-deploy HOST=runner.example.com DISTRO=debian [COUNT=15] [PORT=22] [OWNER=myuser] [REPO=infinito-nexus]
runner-ci-deploy:
	@: "$${HOST:?HOST must be set (e.g. make runner-ci-deploy HOST=runner.example.com DISTRO=debian)}"
	@: "$${DISTRO:?DISTRO must be set (e.g. debian, archlinux)}"
	@"$${PYTHON}" -m cli.administration.deploy.runner "$${HOST}" \
		--roles svc-runner \
		--distribution "$${DISTRO}" \
		--runner-count "$${COUNT:-15}" \
		$${PORT:+--port "$${PORT}"} \
		$${OWNER:+--owner "$${OWNER}"} \
		$${REPO:+--repo "$${REPO}"}

.PHONY: runner-ci-disable
# Disable self-hosted CI runners — routes all deploy jobs back to GitHub-hosted runners.
# Usage: make runner-ci-disable [OWNER=myuser] [REPO=infinito-nexus]
runner-ci-disable:
	@gh variable set CI_SELF_HOSTED_RUNNER_COUNT --body "0" \
		$${OWNER:+--repo "$${OWNER}/$${REPO:-infinito-nexus}"}
	@echo "Self-hosted runners disabled. All CI deploy jobs routed to GitHub-hosted runners."

.PHONY: runner-ci-enable
# Enable self-hosted CI runners by setting CI_SELF_HOSTED_RUNNER_COUNT and INFINITO_TIMEOUT_MULTIPLIER.
# Note: MULTIPLIER default 30 gives ~1 h max wait (60 retries × 30 × 2 s delay) for slow hardware.
# Usage: make runner-ci-enable COUNT=15 [MULTIPLIER=30] [OWNER=myuser] [REPO=infinito-nexus]
runner-ci-enable:
	@: "$${COUNT:?COUNT must be set (e.g. make runner-ci-enable COUNT=15)}"
	@gh variable set CI_SELF_HOSTED_RUNNER_COUNT --body "$${COUNT}" \
		$${OWNER:+--repo "$${OWNER}/$${REPO:-infinito-nexus}"}
	@gh variable set INFINITO_TIMEOUT_MULTIPLIER --body "$${MULTIPLIER:-30}" \
		$${OWNER:+--repo "$${OWNER}/$${REPO:-infinito-nexus}"}
	@echo "Self-hosted runners enabled (count=$${COUNT}, multiplier=$${MULTIPLIER:-30}). CI will split deploy jobs proportionally across GitHub-hosted and self-hosted runners."

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

.PHONY: swarm-app-exec
# Run a one-off command inside a swarm SERVICE container (one replica) on a DinD node.
# Param service: swarm service name (e.g. moodle_moodle | openldap_openldap).
# Param name: cluster id (the app id) used to default the node.
# Param node: full DinD node container (default <name>-swarm-mgr-01).
# Param cmd: shell pipeline executed inside the resolved service container.
swarm-app-exec:
	@test -n '$(service)' || { echo 'usage: make swarm-app-exec service=<svc> [name=<cluster>] [node=<container>] cmd="..."'; exit 2; }
	@node='$(or $(node),$(name)-swarm-mgr-01)' service='$(service)' cmd='$(cmd)' bash scripts/tests/deploy/act/exec/service.sh

.PHONY: swarm-clean
# Reclaim ALL leftover act-swarm state (DinD nodes, NFS sidecars, lab networks, act outer containers) from aborted/wedged roundtrip runs, across every cluster id.
# Note: removes what the docker CLI can; D-state remnants (wedged kernel NFS) need a host docker restart under sudo, or are reported in a no-priv sandbox.
# Note: run BETWEEN swarm runs; it would kill an in-flight one.
swarm-clean:
	@bash scripts/tests/deploy/swarm/utils/clean/all.sh

.PHONY: swarm-clean-stale-nfs
# Recover stale in-namespace NFS mounts from wedged act-swarm nfs-server containers.
# Usage: make swarm-clean-stale-nfs [cid=<container-id-or-name>] [mount=/mnt/gtest]
# Note: needs sudo; may restart containerd/docker only if docker rm still cannot reap the container.
swarm-clean-stale-nfs:
	@CID='$(cid)' NFS_MOUNT='$(mount)' bash scripts/tests/deploy/swarm/utils/clean/stale_nfs.sh

.PHONY: swarm-diagnostic
# Backup/NFS diagnostics for a live swarm-test cluster: backup unit state + journal, NFS mounts, D-state (wedged NFS) processes, rsync/dump processes, disk. Read-only.
# Param name: REQUIRED cluster id (the app id when no name= was passed to swarm-zombie).
# Param node: optional single node container name; default probes mgr-01, nfs-server, bkp-01.
# Param unit: optional systemd unit glob for the journal dump; default svc-bkp-*.
swarm-diagnostic:
	@test -n '$(name)' || { echo 'usage: make swarm-diagnostic name=<cluster-id> [node=<container>] [unit=<glob>]'; exit 2; }
	@SWARM_NAME='$(name)' node='$(node)' unit='$(unit)' bash scripts/tests/deploy/swarm/utils/diagnostic.sh

.PHONY: swarm-down
# Release a named swarm-test cluster (DinD nodes, lab network, act outer container).
# Param name: REQUIRED cluster id matching the one swarm-zombie used (the app id when no name= was passed).
# Note: Safe to run multiple times.
swarm-down:
	@test -n '$(name)' || { echo 'usage: make swarm-down name=<cluster-id> (the app id if you did not pass name=)'; exit 2; }
	@SWARM_NAME='$(name)' INFINITO_KEEP_SWARM_NODES=false bash scripts/tests/deploy/swarm/utils/clean/teardown.sh
	@bash scripts/tests/deploy/act/down_act_outer.sh

.PHONY: swarm-exec
# Run a one-off command inside one of the swarm-test DinD nodes.
# Param node: full container name (e.g. <cluster>-swarm-mgr-01 | <cluster>-nfs-server; cluster = name= or the app id).
# Param cmd: shell pipeline executed inside that container.
swarm-exec:
	@node='$(node)' cmd='$(cmd)' bash scripts/tests/deploy/act/exec/node.sh

.PHONY: swarm-playwright
# Rerun a role-local Playwright spec against the live swarm-test cluster (no redeploy).
# Note: nodes hold a frozen bootstrap copy (not a compose-style mount), so the working-tree's modified+untracked files are copied into the node before rerunning via the same rerun-spec.sh engine as compose-playwright; solve ALL of a role's tests (no pw= narrowing) before any redeploy.
# Usage: make swarm-playwright role=<role> name=<cluster-id> [pw="--grep <pattern>"] [keep=true] [node=<container>]
# Example: make swarm-playwright role=web-svc-logout name=web-app-baserow pw="--grep baserow" keep=true
swarm-playwright:
	@: $${role:?role=<role> required, e.g. role=web-svc-logout}
	@test -n '$(name)' || { echo 'name=<cluster-id> required (the app id when no name= was passed to swarm-zombie)'; exit 2; }
	@node='$(or $(node),$(name)-swarm-mgr-01)' bash scripts/tests/deploy/act/copy_worktree_to_node.sh
	@node='$(or $(node),$(name)-swarm-mgr-01)' cmd="cd $${INFINITO_NODE_SRC_DIR:?} && TEST_E2E_PLAYWRIGHT_NETWORK_HOST=true $(if $(keep),INFINITO_PLAYWRIGHT_KEEP=$(keep) )bash scripts/tests/e2e/rerun-spec.sh $(role) $(pw)" bash scripts/tests/deploy/act/exec/node.sh

.PHONY: swarm-shell
# Drop into an interactive shell on one of the swarm-test DinD nodes.
# Param name: REQUIRED cluster id (the app id when no name= was passed); node defaults to <name>-swarm-mgr-01.
# Param node: full container name to target (overrides the default).
swarm-shell:
	@test -n '$(name)' || { echo 'usage: make swarm-shell name=<cluster-id> [node=<container>]'; exit 2; }
	@SWARM_NAME='$(name)' node='$(node)' bash scripts/tests/deploy/act/shell_node.sh

.PHONY: swarm-zombie
# Run a swarm matrix-app test and leave the cluster alive afterwards for post-mortem inspection.
# Param app: matrix application id (e.g. web-app-baserow).
# Param variant: optional matrix variant index to deploy (default 0); a multi-variant app runs one cluster per swarm-zombie, so pick the round to validate.
# Param disable: optional comma-separated provider keys removed from the test inventory (e.g. matomo,dashboard,prometheus,email,css).
# Param name: optional cluster-id prefix for the container + network names (parallel/named clusters); release with the same name=.
# Note: Use `make swarm-exec` / `make swarm-shell` to inspect, `make swarm-down` to release.
swarm-zombie: install-act
	@test -n '$(app)' || { echo 'usage: make swarm-zombie app=<application_id> [variant=<idx>] [name=<cluster-id>] [disable=<keys>]'; exit 2; }
	@SWARM_NAME='$(or $(name),$(app))' INFINITO_KEEP_SWARM_NODES=false bash scripts/tests/deploy/swarm/utils/clean/teardown.sh
	@bash scripts/tests/deploy/act/down_act_outer.sh
	@ACT_RM=false \
	 ACT_BIND=true \
	 ACT_ENV='INFINITO_KEEP_SWARM_NODES=true;INFINITO_APP_DISCOVERY_RUNNER=host;INFINITO_DEPLOY_MODE=swarm;disable=$(disable);SWARM_NAME=$(or $(name),$(app))' \
	 ACT_WORKFLOW=.github/workflows/test-deploy-swarm.yml \
	 ACT_JOB=swarm \
	 ACT_MATRIX='apps:$(app);variant:$(or $(variant),0)' \
	 ACT_INPUTS='whitelist=$(app)' \
	 bash scripts/tests/deploy/act/workflow.sh

.PHONY: system-purge
# Run the broad low-hardware cleanup routine.
system-purge:
	@bash scripts/system/purge/system.sh

.PHONY: test
# Run the full test pipeline.
# Note: parallel execution with fail-fast.
test: install
	@bash scripts/make/parallel.sh \
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

.PHONY: test-main-merged
# Verify upstream main is fully merged into HEAD (pre-push gate); fetches and fails if the branch lags main.
test-main-merged:
	@bash scripts/git/assert/main_merged.sh

.PHONY: test-merge-signed
# Verify every commit an in-progress merge brings in (HEAD..MERGE_HEAD) is signed (pre-merge-commit gate).
test-merge-signed:
	@bash scripts/git/assert/merge_signed.sh

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