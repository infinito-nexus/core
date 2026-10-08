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
- A role pass has a wall-clock budget: 80 minutes when the injected role stylesheet carries the palette alone, 120 with an in-house carrier or any provisioning change, 180 for a role with several separate surfaces. At the budget, stop polishing, close the pass and list what is left.
- While the role in progress occupies the stack, a second agent MAY prepare the next due role: it reads the upstream sources of that app and drafts outside the repository. It MUST NOT touch the working tree or the stack.

## Gates

- A role pass runs `make test` after its last edit, then the lint target of every file type it touched: `make lint-javascript` and `make lint-playwright` for a spec, `make lint-css` for a stylesheet, `make lint-markdown` for a `TODO.md` or README, `make lint-ansible` for a task, handler or `vars/` file, and the lint target of the language of every script it ships. Mark new files with `git add -N` first. On a red run fix every finding, rerun the failed target, then `make test` once more.
- `make quality-high` runs once per two or three role passes, at every merge of the main branch and before a role is offered for commit. No role pass runs it. On a red gate attribute every finding to its role, fix it there, rerun the failed target, then run the full gate once more.
- Record the tree after every green gate: `GIT_INDEX_FILE=<scratch file> git read-tree HEAD`, then `git add -A` and `git write-tree` with the same `GIT_INDEX_FILE`. A working tree that writes the same hash needs no new gate.
- The baseline deploy of a role runs on the tree the previous pass closed green.

## The stack

- Apps stay deployed between roles. Do not purge ahead of need.
- A deployed UI role that is still due gets its pass before it is removed, also when it only runs as a provider for another role. Schedule that pass directly after the role that needed the provider.
- Purge only when the next deploy does not fit: compare `free -g` and `df -h` with the `mem_limit` and `min_storage` the next role declares in its `meta/services.yml`.
- When it does not fit, remove the fewest finished roles that close the gap with `make compose-entity-purge apps=<role>` and report the measured numbers.
- A finished role that publishes a host port the next deploy binds does not fit either. The mail role holds port 25, which the local mail relay of every deploy with `email` disabled starts on: remove it directly after its pass, and check with `make compose-exec cmd="ss -ltn"` that the port is free before the next deploy.

## One role pass

1. Read `roles/<role>/AGENTS.md` when present. Role changes stay under `roles/<role>/`. A defect of the shared base goes into its own base commit.
2. Deploy against the running stack, on the tree the previous pass closed green (see [Gates](#gates)), with `INFINITO_PLAYWRIGHT_KEEP=true make compose-deploy apps=<role> variant=0 disable=<every disableable service except design>`. Keep the default `initialize` mode, a single pass, no `full_cycle`, no teardown between roles. Start this deploy as soon as the previous pass reported, the stack serves the default palette and the containers of that role are healthy, and verify the previous pass from its logs and screenshots while the deploy runs. A pass runs this one full deploy only.
3. Find the carriers of the app's design in the live stack before you write CSS. List its in-house options first: theming configuration (config, CLI, API or admin setting), theme files or a custom CSS setting, logo and title settings. Then fetch the app's stylesheets through `make compose-exec cmd="curl -sk <url>"` and read its real variable names.
4. Apply the palette through the app's own configuration. An in-house option MUST be used before the injected role stylesheet, in this order:
   - **Theming configuration** (config, CLI, API or admin setting): feed the palette values server side, as [web-app-nextcloud](../../../roles/web-app-nextcloud/tasks/02_manager_ops/08_design.yml) does with `occ theming:config`. Ship no stylesheet.
   - **In-house theme or custom CSS option** (theme file, custom CSS setting): ship the mapping of the app's variables onto the tokens through that option, as [web-app-gitea](../../../roles/web-app-gitea/templates/theme.css.j2) does with themes generated from Gitea's built-in ones.
   - **Injected role stylesheet**, only for what no in-house option reaches:
     - CSS variable design system: map the app's variables onto the tokens in `templates/style.css.j2`.
     - Bootstrap app: set `bootstrap: true` in the role's `design:` entry to link the shared component mapping. Replace the app's hard-coded colors in the role stylesheet, as [web-app-dashboard](../../../roles/web-app-dashboard/files/style.css) does.
     - No design of its own: the shared element defaults apply. The role stylesheet only covers what stays hard-coded.
5. Set logo and title through the app's own mechanism from `lookup('design', application_id)`. Declare the slot sizes the app renders in the role's `design:` entry: measure the box the app gives its logo in every place (expanded and collapsed navigation, sign-in page) and size one slot per shape. Where the app shows a symbol plus a wordmark, declare a wide slot, so the generated lockup carries the title next to the logo. A lone symbol in a wide box is a defect. A slot the app shows on brand-colored chrome (a header, sidebar or sign-in background mapped onto `--design-frame`) gets `frame: true`: its text is then rendered in the frame text color. A slot on a page or panel stays without it.
6. An app with its own theme switch ships `templates/design.js.j2` that mirrors the chosen theme into `data-design-theme` on `<html>`.
7. Iterate without a further full deploy:
   - a changed stylesheet or logo: `make design-sync app=<role> variant=0`,
   - a changed `design.js.j2`, task, template or `meta/` file: `make compose-role-sync role=<role> variant=0`, which re-runs only the app role against the running stack,
   - a changed spec or `playwright.env.j2`: add `pw="--grep design: --grep-invert gallery"` to that call. It stages the spec again, renders its `.env` again and runs the design assertions.
   - a changed spec alone: `make compose-playwright role=<role> pw="--grep design: --grep-invert gallery"`. It reuses the rendered `.env` and also works for a deployed role that a later deploy dropped from the inventory.
8. Write `files/playwright/test-design.js` and register it in `playwright.spec.js`:
   - one test that calls `assertDesignTokens`,
   - `assertToken` on a core surface, the primary action and the body text (the tokens, or the values the app's theming mechanism received), and assertions that logo and title are the configured ones,
   - `assertLightAndDark` on a core surface and `assertReadable` on the core text. Every role MUST support light and dark mode, whatever carries its palette,
   - every open question about the role as an assertion, proven once by a negative control on the running stack. Axes the stack cannot run (SSO with LDAP, Tor, Swarm, other variants) are left to CI,
   - every failure found on the running stack and fixed as an assertion that fails on the state before the fix,
   - one gallery test with at least 20 views of the frontend and, where the app has one, the backend. Prefer settings, administration, forms, lists and detail pages. Log in where the app has accounts and seed showcase content idempotently where a list would be empty.
   - an account for the signed-in interface. When the role provisions none, add an Ansible task to the role that creates the platform administrator through the app's own CLI or API on every deploy, idempotent and with no password in `argv`. Use OIDC instead where the app supports it natively, and run the design pass of the identity provider in the same go. A gallery of visitor pages alone is not a finished pass.
9. Look at views while you iterate with `make design-gallery app=<role> views=<view>[,<view>...]`: it runs the gallery test alone and captures only the named views. Such a run adds its screenshots to the existing ones, so it also recaptures a single view after the full run. Capture the full gallery with `make design-gallery app=<role>` once, on the final design, and look at every screenshot in both modes and both viewports. A role with an in-house carrier also captures the full gallery once before that carrier is applied and keeps a copy as its "before" side. A view whose state only exists with the injected snippets, such as a menu the role's own script opens, carries `afterOnly: true` and is captured on the "after" side only.
10. Check the palette with one further base color, blue `#001f3f`. The design spec MUST stay green with it. No gallery run.
    - `make design-palette app=<role> variant=0 base='#001f3f' sync=design` renders the shared CSS, the role stylesheet and the logos with that base, runs the design assertions and puts the base of the inventory back, also when an assertion fails.
    - A role that bakes palette values at deploy time (theming configuration, theme file, mounted asset) passes `sync=role`, which re-runs the app role for both renders.
    - The spec asserts the text of every primary-filled control against `--design-on-primary`, which is dark on a light base and light on a dark one.
    - A red assertion names a hard-coded color or a value baked at another time than the tokens: fix it and repeat.
    - The target needs an inventory that a full deploy provisioned from a development inventory vars file (`INFINITO_INVENTORY_VARS_FILE`) that defines `DESIGN_BASE_COLOR`.
11. Run `make test` and the lint targets of the file types you touched to green (see [Gates](#gates)).
12. Close the pass on the final state:
    - run `make compose-role-sync role=<role> variant=0`, then the complete role spec with `make compose-playwright role=<role> pw="--grep-invert gallery"`,
    - a pass that changed provisioning (a task, a handler, `vars/`, a template or file the role renders or mounts into a container, `meta/` outside the `design:` entry) runs the role sync twice in a row before that spec. In the second run every provisioning task the pass added MUST report no change.
13. In the step that verifies the pass, publish the gallery as one private Artifact for the role, link it under "Further Resources" in the role README, add the role to the overview Artifact and report the link. Do not wait for the answer; take the next role.
14. Commit only when the operator asks for it, one bundle per role (`roles/<role>/`). On rejection rework from the comment, run the gate again and republish to the same Artifact.

## Rules for the stylesheet

- Colors come from `--design-*` tokens only.
- Text and its background MUST come from the same source. A token color on an app-owned background, or the reverse, voids the contrast guarantee.
- Keep the app's contrast relations: frame against content, panel against page, selected against unselected. Flattening them is a regression.
- Hovered, pressed, open and selected controls use `--design-surface-hover`, `--design-surface-active` and `--design-<fill>-hover`, `--design-<fill>-active`.
- No gradients, no filter effects for state, no hard-coded hex values.
- Delete rules whose selectors match nothing in the deployed app.
- Every `url()` that is neither `data:` nor a `design.urls` value starts with the origin of the app, e.g. `url("{{ XWIKI_URL }}/resources/icons/silk/user.png")`. The stylesheet is served from the CDN, so a root-relative or bare target resolves there. A rule that only repeats an image of the app is deleted instead.

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
- **`design-sync` and scripts.** It renders static files only. An injected script keeps its deployed content because its CSP hash lives in the vhost. `compose-role-sync` renders both.
- **Login URLs under SSO.** The variant that enables `design` usually enables `sso` too, and many apps then redirect their login URL to the identity provider. Sign in through the role's login helper and assert on a page the app renders itself.
- **Parallel spec runs.** Two spec runs of one role share a reports directory and fail with `ENOENT` under `/reports/test-results`. Run one at a time.
- **Overlays caught mid-animation.** `toBeVisible` passes on the first frame of an opening animation, and the gallery helper does not see animations inside shadow roots. A dialog, drawer, menu or sheet view waits in its `prepare` until the panel runs no animation and its opacity is 1. In the screenshots a panel the page shows through, or content that sits inset and half transparent, was captured too early. Check every such view at the mobile viewport in light and dark.
- **Untracked files and the gate.** Lints that enumerate through `git ls-files` skip a new file until `git add -N <file>` marks it.
- **Plain side of the gallery.** A view whose "before" side still carries the injected snippets fails with that message. Give the view the URL its document ends on, and reach a page behind a redirect through its URL instead of a click inside `prepare`.
- **Negative control without a sync.** For a stylesheet fix, strip the fixed rule from the response with `page.route()` in a temporary copy of the test, watch the assertion fail, then delete the route. The stack stays untouched.
- **A deploy that hangs in `Apply state` for `hlth-csp`.** The unit checks every domain on the stack, so the blocked resource can belong to a role of an earlier pass. Read it with `make compose-exec cmd="journalctl -u <unit> --no-pager -n 40 -o cat"`, fix that role, and add the test "every image the role stylesheet references is served" of the XWiki design tests to its spec.
- **Apps that walk `document.styleSheets`.** The injected sheets are linked without `crossorigin`, so app code can neither read nor rewrite their rules, and an app that reads `cssRules` unguarded throws on them. Keep the links that way: with readable sheets LibreTranslate rewrites the `prefers-color-scheme` rule of the shared sheet at load and the tokens stop following the system. Shield such an app in the role's design script, as `roles/web-svc-libretranslate/templates/design.js.j2` does, and pin it with the test "the app's theme switch raises no page error and leaves the injected sheets alone".
- **Gallery links.** An Artifact whose sharing the operator changed can stop accepting updates from the session. Publish a new one, tell the operator that the old link stays on the old state, and update the README link.
