# To-dos

- `make design-queue` keeps listing this role as `new`. The role serves no page of its own: `imprint.html` is served and styled through the vhost of `web-svc-html`, and the design tests in `roles/web-svc-html/files/playwright/test-design.js` cover it. Cause: `UI_LESS_ROLES` in `cli/meta/roles/design/__init__.py` does not hold the role. Options: add it to that set, or let the queue count the spec of the serving role.
