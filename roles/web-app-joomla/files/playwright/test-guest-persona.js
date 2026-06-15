const { test } = require("@playwright/test");
const { runGuestFlow } = require("./personas");

test.use({ ignoreHTTPSErrors: true });

// Persona scenarios.
// Bodies live in the shared helper roles/test-e2e-playwright/files/personas.js
// so every role's persona flow stays consistent.

test("guest: public-landing → auth chain → never authenticated", async ({ page }) => {
  await runGuestFlow(page);
});
