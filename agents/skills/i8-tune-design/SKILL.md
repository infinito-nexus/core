---
name: i8-tune-design
description: >
  Lean design companion of every Infinito.Nexus iteration and roundtrip:
  screenshot the web roles a green run left on the compose stack with the
  designer's own gallery capture and file what a design pass should change
  into the i8-designer queue, without editing a role. Trigger on
  /i8-tune-design, when an iterate routine reaches its tune_design step, or
  when the operator asks for design proposals of the deployed roles.
  Infinito.Nexus specific.
routines:
  - tune_design
---

# Design Tuning

Follow the instructions from AGENTS.md, then follow the `tune_design` routine exactly (run `python -m agents.routines show tune_design` to print its ordered steps). That routine is the source of truth; this skill only routes you there.

It shares the screenshot and gallery code with the `i8-designer` skill: `make design-gallery app=<app>` captures, `python -m cli.meta.roles.design.gallery` names the gallery and its manifest, and `python -m cli.meta.roles.design.propose` files a proposal that `make design-queue` lists as `proposed`.

Stay lean: capture only, judge against the `i8-file-role-style` contract, propose, report. Never edit a role, never commit, never block the loop that ran you; a change you would make yourself is a finding for the designer. Work under the `robot` skill.
