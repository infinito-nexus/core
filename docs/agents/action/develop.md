# Development

## System

- You MUST capture system-wide development requirements in the root `TODO.md` file so global work stays visible in one place.
- When a TODO is completed, you MUST remove it from `TODO.md`.

## Requirements

- When the user asks you to implement a requirement, you MUST follow [Requirements](requirements.md) before writing any code.

## New Apps

- You MUST use [CONTRIBUTING.md](../../../CONTRIBUTING.md) as the SPOT for the general development workflow, testing, review, and the code and development guides.
- You MUST treat the matching Pull Request template described in [Pull Request Templates](../../contributing/artefact/git/pull-request.md) and stored in [PULL_REQUEST_TEMPLATE](../../../.github/PULL_REQUEST_TEMPLATE) as the SPOT for requirements, file checks, validation expectations, and the Definition of Done.
- You MUST read [Role `style.css`](../files/role/style.css.md) BEFORE you implement role-local CSS so you can see how CSS should be implemented before you add or rewrite overrides.
- You MUST read [Role `javascript.js`](../files/role/javascript.js.md) BEFORE you implement role-local JavaScript so you can see how browser-side behavior should be implemented before you add or rewrite injected scripts.
- You MUST read [Role `playwright.env.j2`](../files/role/playwright.env.j2.md) BEFORE you implement role-local Playwright environment templates so the rendered test inputs match the supported user journey.
- You MUST read [Role `playwright.spec.js`](../files/role/playwright.spec.js.md) BEFORE you implement or refactor role-local Playwright specs so end-to-end coverage stays aligned with the role behavior.
- Start from the smallest app-specific change that can be validated locally, then expand only when the requirements or behavior demand it.
- Keep the implementation, local validation, and PR template in sync so the app can be reviewed without guessing the intent.

### Documentation

- You MUST capture open development requirements for a role in its `TODO.md` file so the remaining work stays visible.
- Keep the role's `README.md` as the clear description of what the role can do.
- When a TODO is completed, you MUST promote the finished capability into `README.md` and remove the TODO entry from `TODO.md`.

## Bugs and Warnings

- You MUST treat warnings about the concrete implementation, wiring, or runtime behavior as bugs that should be fixed.
- Do NOT leave implementation warnings unresolved just because they are inconvenient.
- If a warning points to an intentional exception, make the exception explicit and keep the follow-up visible.

## Debugging

- When a development run fails, you MUST switch to [Debugging](debug/README.md) and follow the local-deploy or GitHub-log path that matches the failure source.
- For the shared local retry loop during debugging or development, you MUST follow [Compose Loop](iteration/compose.md).
- Keep long-running runs alive and wait for them to finish unless the user explicitly asks you to steer away from them.

## Review Focus

- You MUST verify that the new app behaves correctly end to end, not just whether it compiles or deploys.
- Prefer fixing the real app bug over adding a comment that explains it away.
- Treat temporary warnings as a signal to remove the underlying problem later, not as a reason to normalize the exception.
