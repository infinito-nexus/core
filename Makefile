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
# Note: see agents/skills/i8-iterate-workflow/SKILL.md.
act-runner-image:
	@bash scripts/tests/deploy/act/build_runner_image.sh

.PHONY: act-workflow
# Run the act-based workflow deploy check.
act-workflow: install-act
	@bash scripts/tests/deploy/act/workflow.sh

.PHONY: agents-integration
# Run the SaaS integration path locally through act: the app matrix with each app deployed together with the agents bundle, local models only, one app after the other.
# Usage: make agents-integration [whitelist="<app ids>"] [priority="<app ids>"]
# Param whitelist: space-separated app ids to integrate (empty: diff vs origin/main)
# Param priority: space-separated app ids to integrate first
agents-integration: install-act
	@whitelist='$(whitelist)' priority='$(priority)' bash scripts/agents/integration.sh

.PHONY: agents-preseed
# Host-pull the agents bundle's large images (for example the Ollama image) before the deploy, so images over the registry cache transfer limit are already loaded.
# Usage: make agents-preseed images="<ref> <ref>"
# Param images: space-separated image refs to host-pull (empty: nothing to preseed)
agents-preseed:
	@images='$(images)' bash scripts/agents/preseed.sh

.PHONY: agents-stop
# Suspend the running agent instances without revoking them (kill switch): the orchestrator blocks every agent key, stops every broker-managed container and disables every agent account; a teardown revokes.
# Usage: make agents-stop orchestrator=<container> cmd="<suspend command>"
# Param orchestrator: deployed orchestrator container name (required)
# Param cmd: the orchestrator's suspend command (required)
agents-stop:
	@orchestrator='$(orchestrator)' cmd='$(cmd)' bash scripts/agents/stop.sh

.PHONY: agents-verify
# Run call-test-agents-local.yml through act (the file the CI runs): deploy the agents bundle and play every agent scenario, printing the result table (id, mode, result, duration, log).
# Usage: make agents-verify [mode=compose|swarm] [scenario=<id>]
# Example: make agents-verify scenario=hacker-bruteforce
# Param mode: compose | swarm; omitted runs both in sequence; swarm needs a worktree slot in 3..10
# Param scenario: a single scenario id replayed against the already-running stack (no act, no redeploy)
agents-verify: $(if $(scenario),,install-act)
	@mode='$(mode)' scenario='$(scenario)' bash scripts/agents/verify.sh

.PHONY: agents-vm-template
# Build the agent VM template of one VM kind from the template directory and its pinned package list only.
# Usage: make agents-vm-template kind=incus|proxmox out=<dir> [dry_run=true]
# Param kind: incus | proxmox
# Param out: directory the build project and the image land in
# Param dry_run: true prints the build commands without running them
agents-vm-template:
	@kind='$(kind)' out='$(out)' dry_run='$(dry_run)' bash scripts/agents/vm-template.sh

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

.PHONY: binfmt
# Make an architecture executable here through emulation.
# Param arch: amd64 | arm64 (default: the platform in INFINITO_DOCKER_PLATFORM)
binfmt:
	@"$${PYTHON}" -m cli.administration.deploy.development binfmt \
		$(if $(arch),--architecture "$(arch)")

.PHONY: bond
# Serve the role bond matrix, where editing a cell rewrites the role's bond.
bond:
	@"$${PYTHON}" -m cli.meta.roles.applications.bond $(args)

.PHONY: bootstrap
# Install dependencies and prepare the project.
bootstrap: install setup

.PHONY: build
# Build the local image.
build: fix-dockerignore
	@IMAGE_TAG="$$(bash scripts/meta/resolve/image/local.sh)" \
		bash scripts/image/build.sh

.PHONY: build-cleanup
# Remove the local toolchain images no registered worktree resolves and no container uses.
# Note: the GHCR package cleanup runs from cron-images-cleanup-ci.yml through scripts/image/cleanup.sh.
build-cleanup:
	@bash scripts/image/cleanup_local.sh

.PHONY: build-dependency
# Pull the build dependency image.
build-dependency:
	@docker pull "$${INFINITO_PARENT_IMAGE:?Run 'make dotenv' to generate the .env single source of truth}"

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

.PHONY: cache-apply
# Install the pinned commit's cache declarations into the running cache stack, never this checkout's own.
# Note: creates the Nexus proxy repos, issues the frontend certs, installs the upstream map the frontend mounts and reloads it, all from the checkout of the pin below INFINITO_CACHE_PIN_ROOT.
# Note: `make compose-up` runs it for every checkout; it names this checkout's `cache:` declarations that differ from the pin and fails while no pin exists. See docs/requirements/096-cache-stack-pin.md.
cache-apply:
	@bash scripts/system/cache/apply.sh

.PHONY: cache-declare
# Pin the commit the shared cache stack runs from, materialize it outside every worktree and apply its cache declarations to the running stack.
# Usage: make cache-declare ref=<commit>
# Note: only the declarer runs it, after the new or changed `cache:` declaration landed on that commit; every worktree then applies the same commit, and the checkouts of earlier commits but the previous pin are pruned.
# Param ref: branch, tag or commit SHA, resolved to the full commit written to INFINITO_CACHE_PIN_FILE; a ref that names no commit, or a commit without the cache pin, is refused.
cache-declare:
	@test -n '$(ref)' || { echo 'usage: make cache-declare ref=<commit>'; exit 2; }
	@bash scripts/system/cache/declare.sh '$(ref)'

.PHONY: cache-evict
# Evict idle cache entries, then the least recently used ones, until every cache fits its cap; refuses when the caps leave less than INFINITO_CACHE_DISK_FLOOR free.
cache-evict:
	@"$${PYTHON}" -m cli.meta.cache.evict

.PHONY: cache-host-sync
# Under sudo, point the host's pacman or apt at the cache stack's caches while INFINITO_CACHE_HOST_SYNC is true, and restore every host file it changed once it is false.
cache-host-sync:
	@sudo env PYTHONDONTWRITEBYTECODE=1 "$${PYTHON}" -m cli.meta.cache.host_sync --sync "$${INFINITO_CACHE_HOST_SYNC}" --shared "$${INFINITO_CACHE_SHARED_HOST_PATH}" --nexus "http://$${INFINITO_CACHE_PACKAGE_REST_HOST}:$${INFINITO_CACHE_PACKAGE_PORT}" --ubuntu-mirrors "$${INFINITO_APT_UBUNTU_MIRRORS}"

.PHONY: cache-status
# Print one JSON object per cache with its path, used bytes, cap, headroom and access-time fallback; the cache pin (pinned and applied commit) goes to stderr.
cache-status:
	@"$${PYTHON}" -m cli.meta.cache.status

.PHONY: cheat
# Print the operator prompt cheatsheet from docs/contributing/tools/agents/cheatsheet.md.
cheat:
	@bash scripts/make/cheatsheet.sh

.PHONY: ci-wait
# Wait for an external CI state (a job log, a run end or a check) with a fixed poll interval and timeout, so no routine needs its own shell loop.
# Usage: make ci-wait kind=job-log|run|check id=<id> interval=<seconds> timeout=<seconds>
# Param kind: job-log | run | check -- the kind of state to wait for
# Param id: the job, run or check id
# Param interval: seconds between polls
# Param timeout: seconds before giving up (non-zero exit)
ci-wait:
	@kind='$(kind)' id='$(id)' interval='$(interval)' timeout='$(timeout)' bash scripts/ci/wait.sh

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
# Remove container-owned generated artefacts (build/).
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

.PHONY: compose-app-exec
# Run a one-off command inside a deployed app container of the local compose stack.
# Usage: make compose-app-exec app=<container> cmd="..."
# Example: make compose-app-exec app=flowise cmd="wget -qO- http://localhost:3000/api/v1/ping"
# Param app: container name of the deployed app.
# Param cmd: shell command to run inside it.
compose-app-exec:
	@test -n '$(app)' || { echo 'usage: make compose-app-exec app=<container> cmd="..."'; exit 2; }
	@app='$(app)' cmd='$(cmd)' bash scripts/tests/deploy/local/exec/app.sh

.PHONY: compose-app-logs
# Dump the logs of a deployed app container of the local compose stack.
# Usage: make compose-app-logs app=<container> [tail=<lines>]
# Example: make compose-app-logs app=litellm tail=80
# Param app: container name of the deployed app.
# Param tail: number of trailing lines (default: 200).
compose-app-logs:
	@test -n '$(app)' || { echo 'usage: make compose-app-logs app=<container> [tail=<lines>]'; exit 2; }
	@app='$(app)' tail='$(tail)' bash scripts/tests/deploy/local/exec/logs.sh

.PHONY: compose-app-restart
# Restart a single deployed app container of the local compose stack.
# Usage: make compose-app-restart app=<container>
# Example: make compose-app-restart app=nextcloud
# Param app: container name of the deployed app.
compose-app-restart:
	@test -n '$(app)' || { echo 'usage: make compose-app-restart app=<container>'; exit 2; }
	@app='$(app)' bash scripts/tests/deploy/local/exec/restart.sh

.PHONY: compose-deploy
# Run the local deploy router.
# Usage: make compose-deploy [mode=...] [apps=...] [purge=...] [type=...] [bundles=...] [disable=...] [full_cycle=...] [variant=...] [debug=...] [hold=...] [timeout=...]
# Example: make compose-deploy mode=reinstall apps=web-app-matomo full_cycle=true
# Note: see scripts/tests/deploy/local/deploy/main.sh for the full routing table.
# Param mode: initialize | reinstall | update (default: initialize)
# Param apps: comma-separated app ids (e.g. web-app-matomo,web-app-keycloak)
# Param purge: true | false (default: false) — purge entities before deploy
# Param bundles: comma-separated bundle names; overrides apps when set
# Param disable: comma-separated service names to render as disabled
# Param full_cycle: true | false — when true, also run the update pass
# Param variant: matrix round index to pin the redeploy to a specific variant
# Param debug: true | false (default: from default.env)
# Param skip_compile: true | false — skip the in-container entry.sh recompile (use when the venv is prebuilt)
# Param hold: true keeps the job's stack after a pool deploy until its release (INFINITO_DEPLOY_VIA_POOL=true only)
# Param timeout: withdraw a pool job still queued after this long, e.g. 30m; unset waits (INFINITO_DEPLOY_VIA_POOL=true only)
compose-deploy:
	@if [ "$${INFINITO_DEPLOY_VIA_POOL:-}" = "true" ]; then \
		exec "$${PYTHON}" -m cli.administration.deploy.pool compose-deploy \
			--hold '$(or $(hold),false)' --timeout '$(timeout)' \
			$(filter-out hold=% timeout=% INFINITO_DEPLOY_VIA_POOL=%,$(MAKEOVERRIDES)); \
	fi; \
	$(if $(debug),INFINITO_DEBUG="$(debug)") \
	 $(if $(skip_compile),INFINITO_SKIP_COMPILE="$(skip_compile)") \
	 bash scripts/tests/deploy/local/deploy/main.sh

.PHONY: compose-down
# Stop the development stack.
compose-down:
	@"$${PYTHON}" -m cli.administration.deploy.development down

.PHONY: compose-entity-purge
# Purge one or more app entities from the container and drop them from the round inventories.
# Usage: make compose-entity-purge apps=<application_id>[,<application_id>...]
# Param apps: application ids to purge
compose-entity-purge:
	@retire=true bash scripts/tests/deploy/local/purge/entity.sh

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

.PHONY: compose-network-recreate
# Recreate the stack's default network after an IPAM change, keeping volumes and reattaching foreign stacks.
compose-network-recreate: install
	@"$${PYTHON}" -m cli.administration.deploy.development recreate

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

.PHONY: compose-role-sync
# Re-run only the role of a deployed app against the running stack (no system stages; the spec runs only with pw=).
# Usage: make compose-role-sync role=<application_id> [variant=<idx>] [task=<task file>] [pw="<playwright args>"] [keep=true] [base='<hex>']
# Example: make compose-role-sync role=web-app-gitea variant=0 pw="--grep design: --grep-invert gallery"
# Example: make compose-role-sync role=web-app-xwiki variant=0 task=06_design.yml
# Param role: deployed application id
# Param variant: matrix round index the app was deployed with
# Param task: task file of the role that runs alone instead of the whole role; it gets the role variables and nothing an earlier task of the role set
# Param pw: Playwright arguments without quotes; when set, the spec of the role is staged again, its .env rendered again and run with them
# Param keep: true lets that spec run capture the design gallery
# Param base: hex base color that replaces the one of the inventory for this run, e.g. base='#001f3f'
compose-role-sync:
	@: $${role:?role=<application_id> required, e.g. role=web-app-gitea}
	@role='$(role)' variant='$(variant)' task='$(task)' pw='$(pw)' keep='$(keep)' base='$(base)' bash scripts/tests/deploy/local/sync/role.sh

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

.PHONY: compose-target-reset
# Recreate the shared target as a bare systemd and sshd machine and rotate the root key the infinito container holds for it.
compose-target-reset:
	@"$${PYTHON}" -m cli.administration.deploy.development target-reset

.PHONY: compose-up
# Start the development stack and reset its shared target.
compose-up: install fix-dockerignore
	@"$${PYTHON}" -m cli.administration.deploy.development up

.PHONY: console
# Interactive REPL for the infinito.nexus CLI, running on the host.
# Note: each line is forwarded to `python -m cli`; Ctrl+C only cancels the current input.
# Note: exit with `exit`, `quit`, or Ctrl+D.
console:
	@"$${PYTHON}" -m cli.console

.PHONY: design-gallery
# Rerun the design spec of a deployed app and copy its screenshots to its gallery, printed by `python -m cli.meta.roles.design.gallery path <app>` (no redeploy).
# Usage: make design-gallery app=<application_id> [views=<view>[,<view>...]] [before=true] [pw="--grep <pattern>"]
# Example: make design-gallery app=web-app-gitea views=dashboard,settings
# Param app: deployed application id
# Param views: comma-separated view names; only these are captured, by the gallery test alone, and added to the existing screenshots
# Param before: true also captures every view with the injected snippets stripped from the document
# Param pw: Playwright arguments without quotes that replace the default `--grep design:`; such a run adds its screenshots to the existing ones
design-gallery:
	@: $${app:?app=<application_id> required, e.g. app=web-app-gitea}
	@app='$(app)' pw='$(pw)' views='$(views)' before='$(before)' bash scripts/tests/design/gallery.sh

.PHONY: design-logos
# Render every app's branding assets (slots and favicon, day and night) from one logo and base color into an HTML preview, without a deploy.
# Usage: make design-logos domain=<primary domain> out=<dir> [logo=<path>] [base='<hex>'] [roles=<role>[,<role>...]]
# Example: make design-logos domain=veen.world out=/tmp/design-logos logo=../computer-inventory/files/galaxyserver/web-svc-design/logo.png base='#8DB33A'
# Param domain: primary domain the role domains are rendered with
# Param out: directory the assets and index.html are written to
# Param logo: logo file; web-svc-design's logo when empty
# Param base: hex base color; web-svc-design's base when empty
# Param roles: comma-separated application ids; every role with a design entry when empty
design-logos:
	@: $${domain:?domain=<primary domain> required, e.g. domain=veen.world}
	@: $${out:?out=<dir> required, e.g. out=/tmp/design-logos}
	@"$${PYTHON}" -m cli.build.logos --domain '$(domain)' --out '$(out)' --logo '$(logo)' --base '$(base)' --roles '$(roles)'

.PHONY: design-palette
# Run the design assertions of a deployed app with another base color and restore the base of the inventory afterwards, also on failure.
# Usage: make design-palette app=<application_id> base='<hex>' sync=<design|role> [variant=<idx>]
# Example: make design-palette app=web-app-gitea variant=0 base='#001f3f' sync=role
# Param app: deployed application id
# Param base: hex base color for the check
# Param sync: design re-renders the static design files, role re-runs the app role for values it bakes at deploy time
# Param variant: matrix round index the app was deployed with
design-palette:
	@: $${app:?app=<application_id> required, e.g. app=web-app-gitea}
	@app='$(app)' base='$(base)' sync='$(sync)' variant='$(variant)' bash scripts/tests/design/palette.sh

.PHONY: design-queue
# Print the roles that are due for a design pass in working order (new roles first, then by version gap, then tune-design proposals).
# Usage: make design-queue [args="--next|--all|--format json"]
# Param args: extra flags for the queue CLI
design-queue:
	@"$${PYTHON}" -m cli.meta.roles.design $(args)

.PHONY: design-sync
# Re-render shared CSS, role style.css and the branding assets of a deployed app (no redeploy; injected scripts stay as deployed).
# Usage: make design-sync app=<application_id> [variant=<idx>] [base='<hex>']
# Param app: deployed application id
# Param variant: matrix round index the app was deployed with
# Param base: hex base color that replaces the one of the inventory for this run, e.g. base='#001f3f'
design-sync:
	@: $${app:?app=<application_id> required, e.g. app=web-app-gitea}
	@app='$(app)' variant='$(variant)' base='$(base)' bash scripts/tests/design/sync.sh

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
dotenv:
	@python3 -m cli.meta.env
	@python3 -m cli.meta.cache

.PHONY: dotenv-force
# Force a clean .env regeneration in a stripped environment.
# Note: avoids stale BASH_ENV INFINITO_* values pinning via setdefault.
dotenv-force:
	@rm -f .env
	@env -i HOME="$${HOME}" PATH="$${PATH}" python3 -m cli.meta.env
	@set -a; . ./.env; set +a; python3 -m cli.meta.cache

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

.PHONY: i18n-extract
# Merge the translatable strings of core and the documentation into the gettext catalogs under locale/.
# Param domain: core | docs (empty: both); with root: the domain whose root/locale/<domain>.yml holds the English source
# Param root: directory holding the locale/ of a custom role or repository outside core (empty: core)
i18n-extract:
	@"$${PYTHON}" -m cli.build.i18n extract $(if $(domain),--domain "$(domain)") $(if $(root),--root "$(root)")

.PHONY: i18n-load
# Report the host load so the translator's crons can decide whether to start the translation lane, without touching Docker directly.
i18n-load:
	@bash scripts/i18n/load.sh

.PHONY: i18n-pause
# Pause the tools services inside the infra runner so a gate can hold the machine lock without them sending requests; the caches keep answering and the tools keep their models and connections.
i18n-pause:
	@"$${PYTHON}" -m cli.administration.infra tools-pause

.PHONY: i18n-prune
# Empty the translations that altered a protected span so the next i18n-translate redoes them.
# Param domain: core | docs (empty: both)
# Param languages: comma-separated ISO 639-1 codes (empty: every language)
i18n-prune:
	@"$${PYTHON}" -m cli.build.i18n prune $(if $(domain),--domain "$(domain)") $(if $(languages),--languages "$(languages)")

.PHONY: i18n-resume
# Resume the tools services inside the infra runner that make i18n-pause paused, with their loaded models and connections intact.
i18n-resume:
	@"$${PYTHON}" -m cli.administration.infra tools-resume

.PHONY: i18n-retry
# Offer the entries a previous run recorded as refused again, after the masking or the damage predicate changed.
# Param domain: core | docs (empty: both)
# Param languages: comma-separated ISO 639-1 codes (empty: every language)
i18n-retry:
	@"$${PYTHON}" -m cli.build.i18n retry $(if $(domain),--domain "$(domain)") $(if $(languages),--languages "$(languages)")

.PHONY: i18n-translate
# Machine-translate the empty and fuzzy entries of the gettext catalogs through the translation gateway, deploying its bundle when it does not answer.
# Param domain: core | docs (empty: both); with root: the domain of the catalogs under root/locale/
# Param root: directory holding the locale/ of a custom role or repository outside core (empty: core)
# Param languages: comma-separated ISO 639-1 codes (empty: every language the gateway serves)
# Param redeploy: true — deploy the bundle even when a gateway already answers (after changing its code or its backends)
# Param gateway: base URL of the shared translation gateway, used as it is and never deployed from here (empty: this checkout's own, deployed when absent)
i18n-translate:
	@"$${PYTHON}" -m cli.build.i18n translate $(if $(domain),--domain "$(domain)") $(if $(root),--root "$(root)") $(if $(languages),--languages "$(languages)") $(if $(filter true,$(redeploy)),--redeploy) $(if $(gateway),--gateway "$(gateway)")

.PHONY: i18n-tune
# Measure the fastest LibreTranslate client settings on this host and record them for `make dotenv`.
# Param language: ISO 639-1 code the sweep translates into (default: de)
i18n-tune:
	@"$${PYTHON}" -m cli.build.i18n tune $(if $(language),--language "$(language)")

.PHONY: infra-down
# Stop the machine-wide infra runner; its volumes and every cache byte stay.
infra-down:
	@"$${PYTHON}" -m cli.administration.infra down

.PHONY: infra-status
# Print the infra runner's state, address, the gateway URL the i18n targets take as gateway= and, per tools project, whether docker compose -p reaches it inside the runner.
infra-status:
	@"$${PYTHON}" -m cli.administration.infra status

.PHONY: infra-up
# Start the machine-wide infra runner on INFINITO_INFRA_SUBNET once; refuses before anything starts when the caps leave less than INFINITO_CACHE_DISK_FLOOR free.
# Param takeover: true stops a running legacy cache stack inside the machine lock right before the runner starts, instead of refusing
infra-up:
	@"$${PYTHON}" -m cli.administration.infra $(if $(filter true,$(takeover)),--takeover) up

.PHONY: infra-update
# Apply changed infra inputs (worktree roots, image, caps) to the running infra runner.
infra-update:
	@"$${PYTHON}" -m cli.administration.infra update

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

.PHONY: install-codex
# Install the Codex CLI at the version roles/dsk-gnt-codex pins, for the unit tests that drive the real client.
install-codex: install
	@"$${PYTHON}" -m utils.install.codex

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

.PHONY: install-node
# Install the Node.js runtime the JavaScript unit suite runs on.
install-node:
	@bash scripts/install/node.sh

.PHONY: install-php
# Install PHP, Composer and the vendor tree the PHP unit suite runs on.
install-php:
	@bash scripts/install/php.sh

.PHONY: install-python
# Install Python tooling.
install-python: install-venv
	@bash scripts/install/python.sh deploy

.PHONY: install-python-dev
# Install Python tooling including lint and dev dependencies.
install-python-dev: install-python
	@bash scripts/install/python.sh dev
	@bash scripts/install/pre-commit.sh

.PHONY: install-ruby
# Install the Ruby interpreter the Ruby unit suite runs on.
install-ruby:
	@bash scripts/install/ruby.sh

.PHONY: install-skills
# Install the agent skills from INFINITO_SKILLS_REPOSITORY into every checkout INFINITO_SKILLS_TARGETS names.
# Example: make install-skills INFINITO_SKILLS_TARGETS='worktree main' INFINITO_SKILLS_REF=<sha>
# Param INFINITO_SKILLS_REPOSITORY: URL or local path of the skills repository; a local path installs its committed state at INFINITO_SKILLS_REF, never its working tree.
# Param INFINITO_SKILLS_REF: branch, tag or commit SHA of the skills repository to install.
# Param INFINITO_SKILLS_TARGETS: space-separated checkouts to install into, each `worktree` (this checkout) or `main` (the primary checkout, first in `git worktree list`); each receives this checkout's agents/skills on top, never its AGENTS.md.
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

.PHONY: iterate-plan
# Plan what an iteration on a diff must run: the unit and lint commands (T0), the inner-loop rows (T1), the pre-push rows and gate (T2) and the CI whitelist (T3), with every cut named.
# Usage: make iterate-plan [base=<ref>] [head=<ref>] [loop=auto] [disable=<keys>|none] [timings=<log|csv>] [format=json]
# Param base: ref the diff starts from (empty: merge base of origin/main and HEAD; nothing is fetched)
# Param head: ref the diff ends at (empty: the working tree, untracked files included)
# Param loop: auto | compose | swarm | playwright | workflow | runner (empty: auto, derived from the diff)
# Param disable: comma-separated provider keys rendered disabled in T1 and T2 (empty: the compose loop's default; none: nothing)
# Param timings: deploy log or role-runtimes CSV that prices the rows in seconds (empty: the declared min_storage)
# Param format: json prints the machine-readable plan (empty: the human form)
iterate-plan:
	@"$${PYTHON}" -m cli.meta.ci.iterate $(if $(base),--base "$(base)") $(if $(head),--head "$(head)") $(if $(loop),--loop "$(loop)") $(if $(disable),--disable "$(disable)") $(if $(timings),--timings "$(timings)") $(if $(format),--format "$(format)")

.PHONY: kernel-loop-load
# Load the kernel loop driver the swarm backup DR drill needs.
# Note: run this on the host; container environments have no modprobe.
kernel-loop-load:
	@sudo bash scripts/system/kernel/loop/load.sh

.PHONY: legal-inventory
# Build the licence inventory of the tree (project licence and every role's declared licence under roles/*/meta/license.yml) so the counsel's checks start from deterministic data.
legal-inventory:
	@bash scripts/legal/inventory.sh

.PHONY: legal-probe
# Probe a running instance through its front proxy for the Set-Cookie headers set before consent and the reachability of the imprint and privacy pages.
# Usage: make legal-probe target=<domain>
# Param target: the instance domain to probe
legal-probe:
	@target='$(target)' bash scripts/legal/probe.sh

.PHONY: lint
# Run all lint checks in parallel.
# Note: each check runs on host or in docker per INFINITO_LINT_RUNNER.
lint: install-lint
	@bash scripts/install/wrapper.sh css packages php ruby sql
	@bash scripts/make/parallel.sh lint-action \
		lint-ansible \
		lint-css \
		lint-dockerfile \
		lint-javascript \
		lint-makefile \
		lint-markdown \
		lint-mermaid \
		lint-packages \
		lint-php \
		lint-playwright \
		lint-python \
		lint-ruby \
		lint-shellcheck \
		lint-sql

.PHONY: lint-action
# Run the GitHub Actions lint checks.
lint-action: install-lint
	@bash scripts/lint/wrapper.sh action

.PHONY: lint-ansible
# Run Ansible lint checks.
# Note: runs ansible's syntax-check plus ansible-lint.
lint-ansible: install-lint setup
	@bash scripts/lint/wrapper.sh ansible

.PHONY: lint-css
# Check that every CSS file parses, via stylelint with an empty rule set.
lint-css: install-lint
	@bash scripts/install/wrapper.sh css
	@bash scripts/lint/wrapper.sh css

.PHONY: lint-dockerfile
# Run hadolint over the root Dockerfile.
lint-dockerfile: install-lint
	@bash scripts/lint/wrapper.sh dockerfile

.PHONY: lint-file
# Run the scope-aware lint tests on one file or directory, without the full gate.
# Usage: make lint-file file=<path> [test=<lint module>]
# Param file: the repository-relative file or directory the lints read
# Param test: one lint module to run alone instead of every scope-aware lint
lint-file: install
	$(if $(file),,$(error lint-file needs file=<path>))
	@lint_scope='$(file)' \
	test_paths='$(or $(test),$(shell grep -rl in_lint_scope tests/lint))' \
	INFINITO_TEST_TYPE="lint" \
	INFINITO_COMPILE=0 \
	bash scripts/tests/code/wrapper.sh scripts/tests/code/run.sh

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

.PHONY: lint-php
# Check that every PHP file parses, via `php -l`.
lint-php: install-lint
	@bash scripts/install/wrapper.sh php
	@bash scripts/lint/wrapper.sh php

.PHONY: lint-playwright
# Verify every role's Playwright spec parses + resolves its helpers.
# Note: stages the spec like test-e2e-playwright does and runs `npx playwright test --list`.
lint-playwright: install-lint
	@bash scripts/lint/wrapper.sh playwright

.PHONY: lint-python
# Run Python lint checks.
lint-python: install-lint
	@bash scripts/lint/wrapper.sh python

.PHONY: lint-role
# Run the scope-aware lint tests on one role, without the full gate.
# Usage: make lint-role role=<role> [test=<lint module>]
# Param role: the role directory name under roles/
# Param test: one lint module to run alone instead of every scope-aware lint
lint-role:
	$(if $(role),,$(error lint-role needs role=<role>))
	@$(MAKE) --no-print-directory lint-file file='roles/$(role)' test='$(test)'

.PHONY: lint-ruby
# Check that every Ruby file parses, via `ruby -c`.
lint-ruby: install-lint
	@bash scripts/install/wrapper.sh ruby
	@bash scripts/lint/wrapper.sh ruby

.PHONY: lint-shellcheck
# Run shellcheck lint checks.
lint-shellcheck: install-lint
	@bash scripts/lint/wrapper.sh shellcheck

.PHONY: lint-sql
# Check that every SQL file parses, via `sqlfluff parse`.
# Note: dialect comes from the nearest .sqlfluff; absent tooling is skipped.
lint-sql: install-lint
	@bash scripts/install/wrapper.sh sql
	@bash scripts/lint/wrapper.sh sql

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
# Autoformat, then run the full test suite (pre-commit gate).
quality:
	@"$(MAKE)" autoformat
	@"$(MAKE)" test

.PHONY: quality-high
# Full gate: quality (autoformat + test) followed by every lint check.
quality-high: quality lint

.PHONY: role-skeleton
# Render a custom web-app-cst-<name> role from a JSON or YAML manifest with the core role skeleton.
# Usage: make role-skeleton manifest=<file> target=<dir>
# Param manifest: manifest file the renderer reads (required); `python -m cli.contributing.role.skeleton schema` lists its fields.
# Param target: directory the role directory web-app-cst-<name> is written into (required).
role-skeleton:
	@test -n '$(manifest)' || { echo 'usage: make role-skeleton manifest=<file> target=<dir>'; exit 2; }
	@test -n '$(target)' || { echo 'usage: make role-skeleton manifest=<file> target=<dir>'; exit 2; }
	@"$${PYTHON}" -m cli.contributing.role.skeleton render --target '$(target)' < '$(manifest)'

.PHONY: role-skeleton-samples
# Render one sample role per database and login choice into roles/web-app-cst-*; make roles-clean removes them.
role-skeleton-samples: install
	@"$${PYTHON}" -m cli.contributing.role.skeleton.samples

.PHONY: role-skeleton-check
# Render the sample roles, run make test and make lint against them, and remove them again, also when a check fails.
role-skeleton-check:
	@trap '"$(MAKE)" roles-clean' EXIT
	@"$(MAKE)" role-skeleton-samples
	@"$(MAKE)" test
	@"$(MAKE)" lint

.PHONY: roles-clean
# Remove every custom role (roles/web-app-cst-*) a pull placed in this checkout and nothing else.
roles-clean:
	@"$${PYTHON}" -m cli.administration.roles.clean

.PHONY: roles-pull
# Pull the custom roles (web-app-cst-*) an inventory declares into roles/ without deploying, removing the ones it no longer declares.
# Usage: make roles-pull inventory=<path>
# Example: make roles-pull inventory=inventories/production/devices.yml
# Param inventory: inventory file whose group_vars/host_vars declare applications.<group>.custom and .source (required).
roles-pull:
	@test -n '$(inventory)' || { echo 'usage: make roles-pull inventory=<path>'; exit 2; }
	@"$${PYTHON}" -m cli.administration.roles.pull '$(inventory)'

.PHONY: roundtrip
# Validate one or more roles through every deploy mode in order (compose, then swarm), stopping at the first failure.
# Param apps: space-separated entries, each <role> or <role>#<variant> (e.g. web-app-nextcloud#8); compose and swarm both deploy that variant, whose logs carry a -v<variant> suffix, a bare <role> deploys variant 0, and an unknown role or undeclared variant exits 2 before the first deploy; default = one role per base cluster, most-complex first (complexity --unique).
# Param modes: optional mode sequence (default "compose swarm"; append k8s once it exists).
# Param keep: true keeps the last entry's swarm cluster, green or failed, because every swarm-zombie run first reclaims the lab subnet and the act outer container an earlier entry kept; empty or false lets swarm-zombie release it once its rescue bundle is on the host.
# Param disable: optional comma-separated provider keys removed from the test inventory (e.g. matomo,dashboard,prometheus,email,design).
# Param preflight: false skips the disk pre-flight of every swarm-zombie run the roundtrip starts.
roundtrip:
	@apps='$(apps)' modes='$(modes)' keep='$(keep)' disable='$(disable)' preflight='$(preflight)' bash scripts/tests/deploy/roundtrip.sh

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

.PHONY: runner-count
# Print the default local runner pool size and its RAM, CPU and disk terms as JSON; INFINITO_RUNNER_COUNT overrides it.
runner-count:
	@"$${PYTHON}" -m cli.meta.runner.count

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

.PHONY: swarm-role-sync
# Re-run only the role of an app against the kept swarm-test cluster from its act job container (no cluster rebuild; the spec runs only with pw=).
# Usage: make swarm-role-sync app=<application_id> [name=<cluster-id>] [variant=<idx>] [pw="<playwright args>"] [keep=true]
# Example: make swarm-role-sync app=web-app-baserow pw="--grep baserow"
# Param app: application id the kept cluster was deployed with
# Param name: cluster id the swarm-zombie run used (default: the app id)
# Param variant: variant index of the round the cluster runs (default 0)
# Param pw: Playwright arguments; when set, make swarm-playwright reruns the spec of the role after a green sync
# Param keep: true lets that spec run capture the design gallery
# Note: needs the nodes and the act job container a failed `make swarm-zombie app=<app> keep=true` leaves up; act removes its container after a green job, and ACT_BIND makes the edits of this worktree live in it.
# Note: a green sync closes no loop; a fresh `make swarm-zombie app=<app>` without keep stays the gate before a role counts as green in swarm.
swarm-role-sync:
	@test -n '$(app)' || { echo 'usage: make swarm-role-sync app=<application_id> [name=<cluster-id>] [variant=<idx>] [pw="<playwright args>"] [keep=true]'; exit 2; }
	@app='$(app)' SWARM_NAME='$(or $(name),$(app))' variant='$(or $(variant),0)' bash scripts/tests/deploy/swarm/sync/role.sh
	@$(if $(pw),$(MAKE) swarm-playwright role='$(app)' name='$(or $(name),$(app))' pw='$(pw)' $(if $(keep),keep='$(keep)'))

.PHONY: swarm-shell
# Drop into an interactive shell on one of the swarm-test DinD nodes.
# Param name: REQUIRED cluster id (the app id when no name= was passed); node defaults to <name>-swarm-mgr-01.
# Param node: full container name to target (overrides the default).
swarm-shell:
	@test -n '$(name)' || { echo 'usage: make swarm-shell name=<cluster-id> [node=<container>]'; exit 2; }
	@SWARM_NAME='$(name)' node='$(node)' bash scripts/tests/deploy/act/shell_node.sh

SWARM_DISTROS = $(or $(distros),$${INFINITO_DISTRO:?})
SWARM_ARCH = $(or $(arch),$(shell bash scripts/meta/resolve/architecture.sh))

.PHONY: swarm-zombie
# Run a swarm matrix-app test, copy the act job's rescue bundle to the host, then release the cluster unless keep=true.
# Param app: matrix application id (e.g. web-app-baserow).
# Param keep: true keeps the cluster and its act outer container up for post-mortem inspection; otherwise both are released on success and on failure.
# Param distros: optional single distro the cluster runs on (default: INFINITO_DISTRO from .env).
# Param variant: optional matrix variant index to deploy (default 0); a multi-variant app runs one cluster per swarm-zombie, so pick the round to validate.
# Param disable: optional comma-separated provider keys removed from the test inventory (e.g. matomo,dashboard,prometheus,email,design).
# Param preflight: false skips the disk pre-flight, which prints the include set the provision step derives with the min_storage each role declares and refuses before act starts when that heuristic total plus the watchdog floor exceeds the lowest free space of Docker's data root and the watchdog's storage roots.
# Param vpn: optional WireGuard axis (auto|enforced|disabled); default disabled.
# Param meshes: optional WireGuard layout a meshed round deploys (default INFINITO_SWARM_MESHES).
# Param name: optional cluster-id prefix for the container + network names; release with the same name=.
# Param arch: architecture the cluster deploys on, amd64 | arm64 (default: the host's own).
# Param network: optional node network mode pinned on the row (clearnet | tor | multi); empty keeps the run's rotation.
# Param step_timeout: optional minute budget for the matrix-deploy step (default 690).
# Param INFINITO_INVENTORY_EXTRA_VARS: optional environment JSON object laid over every round's inventory vars, `applications` merged per app; must not contain ';'.
# Note: With keep=true use `make swarm-exec` / `make swarm-shell` to inspect, `make swarm-down` to release.
# Note: A host-mode-only role has no swarm row; deploy it inside the lightest host row `python -m cli.meta.ci.host_rows --provides <service key> --mode swarm` ranks first.
swarm-zombie: install-act
	@test -n '$(app)' || { echo 'usage: make swarm-zombie app=<application_id> [distros=<distro>] [variant=<idx>] [name=<cluster-id>] [disable=<keys>] [network=<mode>] [keep=true] [preflight=false]'; exit 2; }
	@"$${PYTHON}" -m cli.meta.ci.validate --require-discovery --modes swarm --whitelist '$(app)#$(or $(variant),0)@swarm$(if $(network),+$(network))'
	@SWARM_NAME='$(or $(name),$(app))' INFINITO_KEEP_SWARM_NODES=false bash scripts/tests/deploy/swarm/utils/clean/teardown.sh
	@bash scripts/tests/deploy/swarm/utils/clean/lab_subnet.sh
	@bash scripts/tests/deploy/act/down_act_outer.sh
	@test '$(preflight)' = false || disable='$(disable)' "$${PYTHON}" -m cli.meta.ci.swarm_preflight --app '$(app)' --variant '$(or $(variant),0)'
	@SWARM_NAME='$(or $(name),$(app))' \
	 keep='$(keep)' \
	 ACT_RM=false \
	 ACT_BIND=true \
	 ACT_ENV="INFINITO_KEEP_SWARM_NODES=$(if $(filter true,$(keep)),true,false); \
	 INFINITO_CACHE_SHARED_HOST_PATH=$${INFINITO_CACHE_SHARED_HOST_PATH:-}; \
	 INFINITO_CACHE_HOST_PACMAN_PATH=$${INFINITO_CACHE_HOST_PACMAN_PATH:-}; \
	 INFINITO_APP_DISCOVERY_RUNNER=host; \
	 INFINITO_DEPLOY_MODE=swarm; \
	 INFINITO_INVENTORY_EXTRA_VARS=$${INFINITO_INVENTORY_EXTRA_VARS:-}; \
	 disable=$(disable); \
	 SWARM_NAME=$(or $(name),$(app)); \
	 INFINITO_SWARM_STEP_TIMEOUT_MINUTES=$(or $(step_timeout),690); \
	 INFINITO_GHCR_MIRROR=$${INFINITO_GHCR_MIRROR}; \
	 INFINITO_DISTROS=$(SWARM_DISTROS); \
	 INFINITO_ARCHITECTURES=$(SWARM_ARCH); \
	 INFINITO_ARCHITECTURE=$(SWARM_ARCH)" \
	 ACT_WORKFLOW=.github/workflows/call-test-deploy.yml \
	 ACT_JOB=deploy \
	 ACT_MATRIX="apps:$(app);variant:$(or $(variant),0);mode:swarm" \
	 ACT_INPUTS="whitelist=$(app)#$(or $(variant),0)@swarm$(if $(network),+$(network)) distros=$(SWARM_DISTROS) index=0 sweep=0 modes=swarm vpn=$(or $(vpn),disabled) meshes=$(meshes) disable=$(disable) architectures=$(SWARM_ARCH)" \
	 bash scripts/tests/deploy/swarm/utils/release.sh bash scripts/tests/deploy/act/workflow.sh

.PHONY: system-purge
# Run the broad low-hardware cleanup routine.
system-purge:
	@bash scripts/system/purge/system.sh

.PHONY: test
# Run the full test pipeline.
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
	bash scripts/tests/code/wrapper.sh scripts/tests/code/run.sh

.PHONY: test-integration
# Run the integration test suite.
test-integration: install
	@INFINITO_TEST_TYPE="integration" \
	INFINITO_COMPILE=0 \
	bash scripts/tests/code/wrapper.sh scripts/tests/code/run.sh

.PHONY: test-lint
# Run the lint test suite.
test-lint: install
	@INFINITO_TEST_TYPE="lint" \
	INFINITO_COMPILE=0 \
	bash scripts/tests/code/wrapper.sh scripts/tests/code/run.sh

.PHONY: test-main-merged
# Verify upstream main is fully merged into HEAD (pre-push gate); fetches and fails if the branch lags main.
test-main-merged:
	@bash scripts/git/assert/main_merged.sh

.PHONY: test-merge-signed
# Verify every commit an in-progress merge brings in (HEAD..MERGE_HEAD) is signed (commit-msg gate).
test-merge-signed:
	@bash scripts/git/assert/merge_signed.sh

.PHONY: test-oracle
# Run the suite whose verdict comes from a model (not part of the `test` fan-out).
# Note: brings the tools lane up first, because the checks run inside the stack's container and cannot deploy the model they ask.
test-oracle: install
	@"$${PYTHON}" -m utils.inventory.tools_idle run -- "$${PYTHON}" -m utils.inventory.tools
	@INFINITO_TEST_TYPE="oracle" \
	INFINITO_COMPILE=0 \
	"$${PYTHON}" -m utils.inventory.tools_idle run -- bash scripts/tests/code/wrapper.sh scripts/tests/code/run.sh

.PHONY: test-performance
# Run the runtime-performance suite (not part of the `test` fan-out).
test-performance: install
	@INFINITO_TEST_TYPE="performance" \
	INFINITO_COMPILE=0 \
	bash scripts/tests/code/wrapper.sh scripts/tests/code/run.sh

.PHONY: test-ref
# Run one test against another git ref in a throwaway worktree and let the test prove, by its printed module __file__, that it imported from that ref's tree.
# Usage: make test-ref ref=<ref> test=<path>
# Param ref: the git ref to check out
# Param test: the test path (relative to the repo) to run inside that ref's tree
test-ref:
	@ref='$(ref)' test='$(test)' bash scripts/tests/ref.sh

.PHONY: test-runner-down
# Remove the shared test runner infinito-test-<hash> of this checkout's toolchain image; the next test or lint call starts a new one.
test-runner-down:
	@bash scripts/tests/runner/down.sh

.PHONY: test-security
# Scan every pinned role image of the GHCR mirror with Trivy, Grype and OSV over Syft SBOMs cached by digest (not part of `test`).
test-security:
	@"$${PYTHON}" -m cli.contributing.security.scan \
		--cache-dir build/security \
		--report build/test-reports/security.json \
		--workers 4

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
# Run the unit test suite (every language).
test-unit: test-unit-python test-unit-javascript test-unit-php test-unit-ruby

.PHONY: test-unit-javascript
# Run the JavaScript unit test suite (node:test, no npm dependency).
test-unit-javascript:
	@INFINITO_TEST_TYPE="unit-javascript" \
	bash scripts/tests/code/wrapper.sh scripts/tests/unit/javascript.sh

.PHONY: test-unit-php
# Run the PHP unit test suite (PHPUnit).
test-unit-php:
	@INFINITO_TEST_TYPE="unit-php" \
	bash scripts/tests/code/wrapper.sh scripts/tests/unit/php.sh

.PHONY: test-unit-python
# Run the Python unit test suite.
test-unit-python: install
	@INFINITO_TEST_TYPE="unit" \
	INFINITO_COMPILE=0 \
	bash scripts/tests/code/wrapper.sh scripts/tests/code/run.sh

.PHONY: test-unit-ruby
# Run the Ruby unit test suite (minitest).
test-unit-ruby:
	@INFINITO_TEST_TYPE="unit-ruby" \
	bash scripts/tests/code/wrapper.sh scripts/tests/unit/ruby.sh

.PHONY: worktree-down
# Stop a branch worktree's stack, release the checkout and free its slot.
# Usage: make worktree-down branch=<name> [base=<dir>] [force=true]
# Param branch: branch the worktree was created for (required).
# Param base: parent directory the worktree lives in (default ~/.local/share/worktrees/<domain>/<account>/<repo>).
# Param force: true discards uncommitted changes in the worktree.
worktree-down:
	@test -n '$(branch)' || { echo 'usage: make worktree-down branch=<name> [base=<dir>] [force=true]'; exit 2; }
	@bash scripts/system/worktree/down.sh '$(branch)' '$(base)' '$(or $(force),false)'

.PHONY: worktree-prune
# Drop registrations of worktrees whose directory is gone, freeing the branches they claim.
# Usage: make worktree-prune
worktree-prune:
	@bash scripts/system/worktree/prune.sh

.PHONY: worktree-up
# Check a branch out into an isolated worktree with its own subnet, ports and container names.
# Usage: make worktree-up branch=<name> [base=<dir>]
# Note: the worktree shares the primary checkout's cache stack instead of starting its own; that stack serves the pinned commit's cache declarations, never the worktree's (see `make cache-declare`).
# Param branch: branch to check out (required).
# Param base: parent directory for the worktree (default ~/.local/share/worktrees/<domain>/<account>/<repo>).
worktree-up:
	@test -n '$(branch)' || { echo 'usage: make worktree-up branch=<name> [base=<dir>]'; exit 2; }
	@bash scripts/system/worktree/up.sh '$(branch)' '$(base)'

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
