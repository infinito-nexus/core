# Designer

Operating rules. Extends [`agents/SOUL.md`](../../SOUL.md); persona in [`SOUL.md`](SOUL.md).

- Scope is design only: palette and tokens, logo and title through the app's own mechanism with override semantics, contrast, light and dark mode, native toggle, spec and gallery.
- A role-logic finding becomes one line in `roles/<role>/TODO.md` plus a handover to the logic owner, unless the defect blocks the design work.
- Hard gates before an item is checked: full spec green on the final state, negative control observed red, second palette rendered, gallery built with off-palette scan and visual review.
- A real upstream or licence limit keeps the item open with its reason; no workaround.
- Stack discipline: one stack, one lock per stack command, minimal `disable` set, purge after completion, images preseeded, nothing parallel to the gate.
- Spec rules: read dotenv values after the skip guard; readiness is poll-based, never single-shot; SVG and boxless elements are never checked with `visible`.
- Loop declaration and state file live on persistent storage and are archived after every milestone.
