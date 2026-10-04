# Design Loop

Use this page for bringing the web UI of a role into the corporate design and for the recurring design maintenance of all UI roles.
For the deploy mechanics see the [Compose Loop](iteration/compose.md), for spec iteration the [Playwright Spec Loop](iteration/playwright.md).
For tokens, the cascade layer and the role stylesheet contract see [style.css](../../contributing/artefact/files/role/style.css.md).

## When to use

- A role with a web UI has no design pass yet, or its app version or the shared design base moved since its last pass.
- A recurring agent maintains the design of every UI role.

## The queue

- `make design-queue` prints the roles that are due, in the order you MUST work them:
  1. `new`: roles without a committed `files/playwright/test-design.js`, newest role first.
  2. `stale`: roles whose image version moved since their last design pass, largest version gap first, followed by roles for which only the shared design base changed.
  3. Ties: the most recently changed role first.
- `review` roles carry an uncommitted design spec. They wait for the operator and MUST NOT be picked again unless the operator rejected their gallery.
- `current` roles need no work.
- You MUST work exactly one role and run exactly one compose stack at a time.

## Cadence

- The loop iterates every 30 minutes. On each tick: read the queue, continue the role in progress, or start the first due role.
- A long-running deploy, gate or gallery run wakes the loop on completion. The 30 minute tick is the fallback.
- When nothing is due and no gallery awaits an answer, report the status matrix (approved, in review, rejected, due) and wait for the next tick.

## One role pass

1. Read `roles/<role>/AGENTS.md` when present. Role changes stay under `roles/<role>/`. A defect of the shared base goes into its own base commit.
2. Run `make quality-high` to green, then deploy against the running stack with `INFINITO_PLAYWRIGHT_KEEP=true make compose-deploy apps=<role> variant=0 disable=<every disableable service except design>`. Keep the default `initialize` mode, a single pass, no `full_cycle`, no teardown between roles.
3. Find the carrier of the app's colors in the live stack before you write CSS. Fetch the app's stylesheets through `make compose-exec cmd="curl -sk <url>"` and read its real variable names.
4. Apply the palette through the strongest carrier the app offers:
   - **Theming mechanism** (config, CLI or API): feed the palette values server side, as [web-app-nextcloud](../../../roles/web-app-nextcloud/tasks/02_manager_ops/08_design.yml) does with `occ theming:config`. Ship no stylesheet.
   - **CSS variable design system**: map the app's variables onto the tokens in `templates/style.css.j2`, as [web-app-gitea](../../../roles/web-app-gitea/templates/style.css.j2) does.
   - **Bootstrap app**: the shared mapping applies. Replace the app's hard-coded colors in the role stylesheet, as [web-app-dashboard](../../../roles/web-app-dashboard/files/style.css) does.
   - **No design of its own**: the shared element defaults apply. The role stylesheet only covers what stays hard-coded.
5. Set logo and title through the app's own mechanism from `lookup('design', application_id)`. Declare the slot sizes the app renders in the role's `design:` entry.
6. An app with its own theme switch ships `templates/design.js.j2` that mirrors the chosen theme into `data-design-theme` on `<html>`.
7. Iterate the stylesheet with `make design-sync app=<role> variant=0`. A changed `design.js.j2`, task or template needs `make compose-deploy mode=update apps=<role> variant=0 disable=<same list>`.
8. Write `files/playwright/test-design.js` and register it in `playwright.spec.js`:
   - one test that calls `assertDesignTokens`,
   - assertions that a core surface, the primary action and the body text take the palette colors (the tokens, or the values the app's theming mechanism received), and that logo and title are the configured ones,
   - one gallery test with at least 20 views of the frontend and, where the app has one, the backend. Prefer settings, administration, forms, lists and detail pages. Log in where the app has accounts and seed showcase content idempotently where a list would be empty.
9. Capture with `make design-gallery app=<role>` and look at every screenshot in both modes and both viewports.
10. Run `make quality-high` to green.
11. Publish the gallery as one private Artifact for the role, link it under "Further Resources" in the role README and report the link. Do not wait for the answer; take the next role.
12. On approval stage only `roles/<role>/`, commit, and ask the operator to push. On rejection rework from the comment, run the gate again and republish to the same Artifact.

## Rules for the stylesheet

- Colors come from `--design-*` tokens only.
- Text and its background MUST come from the same source. A token color on an app-owned background, or the reverse, voids the contrast guarantee.
- Keep the app's contrast relations: frame against content, panel against page, selected against unselected. Flattening them is a regression.
- Hovered, pressed, open and selected controls use `--design-surface-hover`, `--design-surface-active` and `--design-<fill>-hover`, `--design-<fill>-active`.
- No gradients, no filter effects for state, no hard-coded hex values.
- Delete rules whose selectors match nothing in the deployed app.

## Review checklist for every screenshot

- Text, icons and control borders are readable against their background in light and in dark mode.
- Hover, focus, pressed, open and selected states are visible and readable.
- The view shows the state it is named after. A view that equals the start page is dead and MUST be replaced.
- No image is broken, no menu is clipped, nothing is caught in the middle of an animation.
- "Before" and "after" show the same page state.

## Traps

- **Measure, do not guess.** Add a temporary `diag:` test to the role spec, run it with `make compose-exec cmd="bash scripts/tests/e2e/rerun-spec.sh <role> --grep diag:"`, read the computed styles or console errors, then delete the test.
- **Animated apps.** `captureDesignGallery` waits up to 5 seconds for finite animations before each screenshot. An app that animates longer, or that swaps content after the animation, needs its own wait in the view's `prepare`.
- **Framework state colors.** Frameworks hard-code hover, active and disabled colors per button variant. Map every state variable, not only the resting one.
- **Legacy stylesheets.** A role stylesheet inherited from before the overhaul may assign variables the app never reads. Verify every mapped name against the app's real CSS.
- **`getComputedStyle` and visited links.** It reports the unvisited color. A link that looks different in a screenshot is not proven different by the computed value.
- **`design-sync` and scripts.** It renders static files only. An injected script keeps its deployed content because its CSP hash lives in the vhost.
- **Gallery links.** An Artifact whose sharing the operator changed can stop accepting updates from the session. Publish a new one, tell the operator that the old link stays on the old state, and update the README link.
