# 068 - Beaver Mascot Animations

## User Story

As a user of an Infinito.Nexus deployment, I want the Infinito.Nexus beaver to show me what the platform is doing while I wait, when something breaks and when I need help, so that waits are visible, errors read friendly and help is one hover away on every app.

## Decisions (operator-confirmed 2026-10-31)

1. The beaver model, its parts, expressions, poses, props, file list, formats and licence come from the avatar repository (`infinito-nexus/avatar`, requirement `docs/requirements/001-beaver-avatar.md`, and its README once `dist/` exists). This requirement and its code link there for every part id, expression or file and copy none of them; only the ids in the generated `dist/svg/*.svg` are an interface.
2. Every animation is SVG plus CSS, styled after the Infinito.Nexus logo (`assets/img/logo.png`, blue and white). The logout clock is plain JavaScript. No animation library and no 3D renderer is added.
3. The animations live in one new core role that serves its assets same-origin to every consumer; the consumers (Keycloak login theme, logout panel, dashboard, proxy error pages, app injection) reference that role and carry no copy of the beaver.
4. Implementation starts once the avatar repository has published `dist/`.

## Acceptance Criteria

### Role and assets

- [ ] A new role serves the beaver SVG, the animation stylesheets and the logout clock script same-origin under one path on every vhost that renders an animation, and no consumer role holds a copy of the beaver SVG.
- [ ] The role pins the avatar release it serves and states the avatar repository as the source of the SVG in its README; no part id, expression name or file name is written into the role except where a stylesheet or script addresses that id.
- [ ] Every animation uses only the colours of the Infinito.Nexus logo.
- [ ] Every animation stops moving under `prefers-reduced-motion: reduce` and still shows the static beaver.
- [ ] Every page that shows an animation renders a static beaver and its text with JavaScript disabled.
- [ ] The CSP of every vhost that shows an animation allows the role's assets without `unsafe-inline` or a new external origin.

### Logout clock

- [ ] After a logout, the Keycloak login page shows the beaver with a running clock that counts down the configured `services.sso_proxy.cookie_refresh` of `web-app-keycloak`, read from that key and not hard-coded.
- [ ] When the countdown ends, the page states that every session is signed out on every network.
- [ ] With JavaScript disabled, the page shows the same wait as text with the configured interval.

### Logout progress

- [ ] While the per-network conductor sweep runs, the beaver ticks off each domain the conductor reports done.
- [ ] On the conductor's `partial` report, the beaver shows a still-lit device next to the partial-logout message.

### Error and maintenance pages

- [ ] The proxy's 502 and 503 pages show the beaver plugging its cable back in.
- [ ] The maintenance page shows the beaver building its dam with both props put down.
- [ ] The 404 page shows the beaver searching with a magnifier.
- [ ] Each error page keeps its status code and its existing text.

### Loading and empty states

- [ ] While the dashboard loads an app into its iframe, the beaver gnaws a log as the loading indicator, and it disappears once the app has loaded.
- [ ] An empty dashboard list shows the beaver pointing at the first step.

### Beaver lodge

- [ ] Every app page shows a small beaver lodge in the bottom-right corner, injected the same way the logout control is injected, without covering app controls on a 360 px wide viewport.
- [ ] On hover or keyboard focus, the beaver comes out of the lodge and offers help in a speech bubble; the bubble is reachable and closable by keyboard and announces itself to screen readers.
- [ ] Without requirement 069 the bubble offers links into the platform documentation; with 069 deployed it opens the help assistant.
- [ ] A user can hide the lodge, and the choice persists in the browser.

### Tests

- [ ] A unit test renders every consumer template and asserts that it references the role's asset path and contains no inline beaver SVG.
- [ ] A Playwright spec checks the logout clock with JavaScript on and off, an error page, the dashboard loading state and the lodge's hover, keyboard and hide behaviour.
