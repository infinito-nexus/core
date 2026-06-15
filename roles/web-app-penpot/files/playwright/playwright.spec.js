// Penpot Playwright spec — orchestration only. Shared state, login helpers and
// the lifecycle hook live in `_shared.js`; each login surface is registered
// from its own `test-login-*.js` companion so every scenario stays atomar and
// individually inspectable.

const shared = require("./_shared");
const { test, expect, skipUnlessServiceEnabled, runGuestFlow, runBiberFlow, runAdminFlow, env, penpotOidcLogin } = shared;

test.use({ ignoreHTTPSErrors: true });

test.beforeEach(async ({ page }) => {
  expect(env.baseUrl, "PENPOT_BASE_URL must be set").toBeTruthy();
  expect(env.canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
  await page.context().clearCookies();
});

test("baseline: Penpot responds on the canonical domain with TLS", async ({ page }) => {
  const r = await page.goto(`${env.baseUrl}/`);
  expect(r, "Expected Penpot response").toBeTruthy();
  expect(r.status(), "Expected Penpot front page status < 500").toBeLessThan(500);
  expect(
    r.url().includes(env.canonicalDomain),
    `Expected canonical domain "${env.canonicalDomain}" to back the Penpot URL`,
  ).toBe(true);
  expect(r.headers()["strict-transport-security"], "Penpot must emit HSTS").toBeTruthy();
});

// Login surfaces — one companion per method × persona.
require("./test-login-native").register(shared);
require("./test-login-oidc-admin").register(shared);
require("./test-login-oidc-biber").register(shared);
require("./test-login-ldap-admin").register(shared);
require("./test-login-ldap-biber").register(shared);
require("./test-seaweedfs");

test("project: administrator creates a design project", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  test.setTimeout(120_000); // OIDC round-trip + dashboard project creation
  await penpotOidcLogin(page, env.adminUsername, env.adminPassword);
  const projectName = `pw-project-${Date.now()}`;
  const addProject = page
    .getByRole("button", { name: /new project|add project|create.*project/i })
    .or(page.locator('[data-testid="add-project"], [data-test="add-project"]'))
    .first();
  await expect(addProject, "Expected a create-project control on the dashboard").toBeVisible({ timeout: 60_000 });
  await addProject.click();
  const nameInput = page.locator('.project-name input, input[type="text"]:visible, [contenteditable="true"]:visible').first();
  await nameInput.fill(projectName);
  await nameInput.press("Enter");
  await expect(page.getByText(projectName, { exact: false }).first()).toBeVisible({ timeout: 30_000 });
});

test("asset: administrator uploads an image asset into a design file", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  test.setTimeout(180_000); // OIDC + editor load + image upload
  await penpotOidcLogin(page, env.adminUsername, env.adminPassword);

  // Open Drafts and create a new file; Penpot navigates into the workspace editor.
  await page.getByText("Drafts", { exact: true }).first().click();
  const newFile = page.getByText(/\+\s*New File/i).first();
  await expect(newFile, "Expected a create-file control in Drafts").toBeVisible({ timeout: 60_000 });
  await newFile.click();
  await expect.poll(() => page.url(), { timeout: 90_000, message: "expected to enter the Penpot workspace editor" })
    .toContain("/workspace");

  // Upload a small PNG into the file via the workspace image file input.
  const validPng = shared.validImagePng();
  const fileInput = page.locator('input[type="file"]').first();
  await fileInput.waitFor({ state: "attached", timeout: 60_000 });
  await fileInput.setInputFiles({ name: "pw-asset.png", mimeType: "image/png", buffer: validPng });

  // The uploaded image becomes a board/shape on the canvas; assert Penpot
  // acknowledges the upload (a layer/element named after the file appears).
  await expect(page.getByText(/pw-asset/i).first()).toBeVisible({ timeout: 60_000 });
});

// Persona scenarios. Bodies live in the shared persona helpers. Penpot's login
// is an in-app "OpenID" provider entry (clickable text, not a `login`/`sign-in`
// link) and its logout sits behind an SPA user menu the generic persona helper
// does not recognise, so the authenticated biber / administrator persona
// journeys are declared blocked (PERSONA_*_BLOCKED, mirrors web-app-taiga).
// Their real auth paths are exercised by the dedicated login companions above.

test("guest: public-landing → auth chain → never authenticated", async ({ page }) => {
  await runGuestFlow(page);
});

test("biber: app → role interaction → universal logout", async ({ page }) => {
  await runBiberFlow(page);
});

test("administrator: app → admin interaction → universal logout", async ({ page }) => {
  await runAdminFlow(page);
});
