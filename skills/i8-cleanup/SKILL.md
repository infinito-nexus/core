---
name: i8-cleanup
description: >
  Free the disk space and /tmp that agents filled on an Infinito.Nexus host:
  run the portable `cleanup` skill and apply this repository's rules for
  stacks, worktrees, images, shared caches and teardown targets on top of it.
  Trigger on /i8-cleanup or when the operator asks to clean up after agents in
  this repository. Infinito.Nexus specific.
---

# Cleanup After Agents

Follow the instructions from AGENTS.md, then run the `cleanup` skill (installed
by `make install-skills`) and apply the rules below on top of it; where a rule
here is stricter, it wins. This skill never runs under the `robot` skill.

## Attribution

- **Stacks**: group containers, volumes and networks by their
  `com.docker.compose.project` label and map each project to its worktree with
  `git worktree list`. A stack consists of the DinD container, its `-coredns`
  sidecar, the volumes `<project>_docker` (the nested Docker of the whole
  deployment), `<project>_infinito`, `<project>_letsencrypt`, the network
  `<project>_default` and the image `<project>/debian:latest`.
- **Orphaned images**: a `<project>/debian:latest` whose worktree no longer
  exists has no owner.
- **Shared cache stack**, claimed by every session and never a candidate:
  `infinito-registry-cache`, `infinito-package-cache`,
  `infinito-package-cache-frontend`, `infinito-coredns`, the network
  `infinito-nexus-core_default` and `/var/cache/infinito/core/cache`.
- **Act and swarm**: `local/act-runner-fixed:latest`,
  `infinito-swarm-node:latest`, the volume `act-toolcache` and `~/.cache/act`
  stay while any peer runs a swarm step or a roundtrip.
- **`infinito-i18n-libretranslate`**: model weights; downloading them again
  needs an `allowed_domains` entry. High risk.
- **/tmp**: deploy and gate logs follow `/tmp/<slug>-<N>.log`. A log whose name
  contains a role name can be requirement evidence; it stays unless its
  session releases it. Session scratch lives under
  `/tmp/claude-<uid>/<project-dir>/<session-id>/`.
- **Archive duties**: before deleting a scratchpad, grep the memory directory
  for its name and for `archiv`. The designer generator dirs
  (`scratchpad/cssmap/`) go to `refs/backup/designer/tools/` first.

## Teardown and delete paths

| Target | Command | Destroys |
| ------ | ------- | -------- |
| Stack of a worktree | `make -C <worktree> compose-down` | containers and volumes including `<project>_docker`; the next deploy needs `mode=initialize` |
| Stack, checkout and slot | `make worktree-down branch=<branch>` | as above plus the checkout; refuses uncommitted changes |
| One app inside a stack | `make -C <worktree> compose-entity-purge apps=<app>` | the app's containers, volumes and inventory group; the output must name `removed '<app>' from inventory` |
| One swarm cluster | `make swarm-down name=<cluster>` | its DinD nodes, lab network and act outer container |
| Every act-swarm leftover | `make swarm-clean` | all clusters including in-flight runs; only when no peer runs a swarm step |
| Container-owned files in a checkout | `make -C <worktree> clean-container-owned` or `make -C <worktree> compose-exec cmd='rm -rf <path>'` | the named paths |
| The dev container's own `/tmp` (tmpfs) | `make compose-exec cmd='df -h /tmp'`, then `make compose-exec cmd='rm -rf /tmp/playwright-transform-cache-0'` | the Playwright transform cache |

- Run `compose-down`, `compose-entity-purge` and `worktree-down` for another
  worktree with the inherited `INFINITO_*` variables stripped:
  `env $(printenv | grep -o -E '^INFINITO_[A-Z0-9_]+' | sed 's/^/-u /') make ...`.
- A worktree that ran a container gate keeps container-owned files: remove
  them from inside it with `make compose-exec` before `make worktree-down`.
- After removing `<project>/debian` images, offer
  `docker builder prune --filter until=24h`; their layers stay in the build
  cache until then.
- When the classifier refuses a purge or teardown, report the exact `make`
  command to the operator.

## Never

- `make system-purge`: runs `docker compose down --volumes` and
  `docker system prune -a --volumes` across every stack.
- `make clean-cache`: wipes `/var/cache/infinito/core/cache` and stops the
  cache containers every deploy builds through.
- `make worktree-prune` as a cleanup step: it also drops detached-HEAD
  registrations whose commits may be reachable only through them.

Begin by clarifying every open requirement with the `active-listening` skill.
The task is finished when the `cleanup` report shows the before and after sizes
and every peer that answered has been told what was removed near its items.
