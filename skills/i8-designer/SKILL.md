---
name: i8-designer
description: >
  Bring the web UI of Infinito.Nexus roles into the corporate design and keep it
  there: take the next due role from the design queue, style frontend and
  backend through the palette, capture the before/after gallery and hand it to
  the operator for approval. Runs as a loop that iterates every 30 minutes. Use
  when the operator asks for design work on a role, for the recurring design
  maintenance, or for /i8-designer. Infinito.Nexus specific.
---

Follow the instructions from AGENTS.md, then follow the procedure in `docs/agents/action/design.md` (relative to the Infinito.Nexus repository root) exactly. That document is the source of truth; this skill only routes you there.

Take the role from the operator's message when one is named. Otherwise run `make design-queue` and take the first due role: new roles first (newest first), then roles whose image version moved since their last design pass (largest gap first) or whose shared design base changed, ties broken by the most recently changed role.

This skill is a loop. Run it self-paced with a 30 minute tick (`/loop 30m /i8-designer`, or the host's equivalent wake-up): each tick continues the role in progress or starts the next due one, and a finished deploy, gate or gallery run wakes it earlier. Never wait on an approval; publish the gallery, report the link and move on. Stop the loop only when the queue is empty and no gallery awaits an answer, and report the status matrix then.

The procedure fixes the deploy command (single pass against the running stack, no reinstall, no `full_cycle`); the inspect-before-redeploy rules of the `i8-iterate-compose` skill still apply after a failed deploy, and every gate runs through the `i8-quality-high` skill. Work under the `robot` skill; put a question to the operator only where the procedure demands an explicit confirmation (commits, pushes, changes to `roles/test-e2e-playwright/`).
