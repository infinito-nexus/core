---
name: i8-designer
description: >
  Bring the web UI of Infinito.Nexus roles into the corporate design and keep it
  there: take the next due role from the design queue, style frontend and
  backend through the palette, capture the before/after gallery and hand it to
  the operator for approval. Runs as a loop that iterates every 30 minutes. Use
  when the operator asks for design work on a role, for the recurring design
  maintenance, or for /i8-designer. Infinito.Nexus specific.
routines:
  - design
---

Follow the instructions from AGENTS.md, then follow the `design` routine exactly (run `python -m agents.routines show design` to print its ordered steps). That routine is the source of truth; this skill only routes you there.

Take the role from the operator's message when one is named. Otherwise run `make design-queue` and take the first due role: new roles first (newest first), then roles whose image version moved since their last design pass (largest gap first) or whose shared design base changed, ties broken by the most recently changed role.

This skill is a loop. Run it self-paced with a 30 minute tick (`/loop 30m /i8-designer`, or the host's equivalent wake-up): each tick continues the role in progress or starts the next due one, and a finished deploy, gate or gallery run wakes it earlier. Never wait on an approval; publish the gallery, report the link and move on. Stop the loop only when the queue is empty and no gallery awaits an answer, and report the status matrix then.

The procedure fixes the deploy command (single pass against the running stack, no reinstall, no `full_cycle`); the inspect-before-redeploy rules of the `i8-iterate-compose` skill still apply after a failed deploy, and every gate runs through the `i8-quality-high` skill. Work under the `robot` skill; put a question to the operator only where the procedure demands an explicit confirmation (commits, pushes, changes to `roles/test-e2e-playwright/`).

Stylesheet contract (tokens only, `url()` origin, contrast, state colors): the `i8-file-role-style` skill and the `style.css.md` SPOT.

## Parallel passes (operator-ordered)

Up to four passes on one stack. Every stack, test or lint command runs `flock /tmp/design-pass.lock <command>`, one command per lock; editing and reading sources need no lock. Caps via `flock … timeout <s> <command>`: 300 diag or single-view, 900 spec / full gallery / palette `sync=design`, 2700 palette `sync=role`, 1500 role-sync, 600 `make test` or a lint. Probe the lock with `timeout 570 flock /tmp/design-pass.lock true` (124 = still held).

## Traps

- A readable injected sheet lets LibreTranslate rewrite the shared sheet's `prefers-color-scheme` at load; keep the injected links without `crossorigin` and shield such apps in the role `design.js`.
- A broken `url()` in any role stylesheet fails the stack-wide `hlth-csp` unit for every role; read its journal before blaming your own change.
- `getComputedStyle` returns the unvisited link color; a screenshot difference is not proven by it.
- The gallery waits 5s for finite animations; a longer or post-animation view needs its own wait in `prepare`.
