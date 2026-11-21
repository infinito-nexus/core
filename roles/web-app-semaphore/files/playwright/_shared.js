const { expect, test } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

const {
  apiFetchOnion,
  decodeDotenvQuotedValue,
  gotoOnion,
  normalizeBaseUrl,
  performKeycloakLoginForm,
  requireDotenvValue,
  withLdapGroupMember,
} = require("./personas");
const { isServiceEnabled, skipUnlessServiceDisabled, skipUnlessServiceEnabled } = require("./service-gating");
const keycloakAdmin = require("./personas/utils/keycloak");

const oidcEnabled         = isServiceEnabled("sso");
const loginMethodLdap     = process.env.LOGIN_METHOD_LDAP_ENABLED === "true";
const loginMethodNative   = process.env.LOGIN_METHOD_NATIVE_ENABLED === "true";
const passwordFormShown   = loginMethodLdap || loginMethodNative;
const oidcIssuerUrl       = normalizeBaseUrl(requireDotenvValue(process.env.OIDC_ISSUER_URL, "OIDC_ISSUER_URL"));
const semaphoreBaseUrl    = normalizeBaseUrl(process.env.SEMAPHORE_BASE_URL || "");
const adminUsername       = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const adminPassword       = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);
const breakglassUsername  = decodeDotenvQuotedValue(process.env.BREAKGLASS_USERNAME);
const breakglassPassword  = decodeDotenvQuotedValue(process.env.BREAKGLASS_PASSWORD);
const biberUsername       = decodeDotenvQuotedValue(process.env.BIBER_USERNAME);
const biberPassword       = decodeDotenvQuotedValue(process.env.BIBER_PASSWORD);
const biberEmail          = decodeDotenvQuotedValue(process.env.BIBER_EMAIL);
const canonicalDomain     = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN);
const keycloakBaseUrl     = normalizeBaseUrl(requireDotenvValue(process.env.KEYCLOAK_BASE_URL, "KEYCLOAK_BASE_URL"));
const realmName           = decodeDotenvQuotedValue(process.env.KEYCLOAK_REALM_NAME);
const superAdminUsername  = decodeDotenvQuotedValue(process.env.SUPER_ADMIN_USERNAME);
const superAdminPassword  = decodeDotenvQuotedValue(process.env.SUPER_ADMIN_PASSWORD);
const keycloakAdminRealm  = decodeDotenvQuotedValue(process.env.KEYCLOAK_ADMIN_REALM);
const keycloakAdminCliClientId = decodeDotenvQuotedValue(process.env.KEYCLOAK_ADMIN_CLI_CLIENT_ID);
const userGroupPath       = decodeDotenvQuotedValue(process.env.RBAC_USER_GROUP_PATH);
const biberDn             = requireDotenvValue(process.env.BIBER_LDAP_DN, "BIBER_LDAP_DN");
const userGroupDn         = requireDotenvValue(process.env.LDAP_USER_GROUP_DN, "LDAP_USER_GROUP_DN");
const operatorGroupPath   = requireDotenvValue(process.env.RBAC_OPERATOR_GROUP_PATH, "RBAC_OPERATOR_GROUP_PATH");
const operatorGroupDn     = requireDotenvValue(process.env.LDAP_OPERATOR_GROUP_DN, "LDAP_OPERATOR_GROUP_DN");
const projectName         = requireDotenvValue(process.env.SEMAPHORE_PROJECT_NAME, "SEMAPHORE_PROJECT_NAME");
const runnerImageTag      = requireDotenvValue(process.env.SEMAPHORE_RUNNER_IMAGE_TAG, "SEMAPHORE_RUNNER_IMAGE_TAG");
const appControlTargetId  = requireDotenvValue(process.env.APP_CONTROL_TARGET_ID, "APP_CONTROL_TARGET_ID");
const appControlTargetUrl = normalizeBaseUrl(requireDotenvValue(process.env.APP_CONTROL_TARGET_URL, "APP_CONTROL_TARGET_URL"));
const pausedLanguage      = requireDotenvValue(process.env.APP_CONTROL_PAUSED_LANGUAGE, "APP_CONTROL_PAUSED_LANGUAGE");
const dashboardStatusEnabled = process.env.DASHBOARD_STATUS_ENABLED === "true";
const dashboardBaseUrl    = normalizeBaseUrl(decodeDotenvQuotedValue(process.env.DASHBOARD_BASE_URL));
const pausedCatalogue     = JSON.parse(
  requireDotenvValue(process.env.APP_CONTROL_PAUSED_CATALOGUE_JSON, "APP_CONTROL_PAUSED_CATALOGUE_JSON"),
);
const pausedContacts      = JSON.parse(
  requireDotenvValue(process.env.APP_CONTROL_PAUSED_CONTACTS_JSON, "APP_CONTROL_PAUSED_CONTACTS_JSON"),
);

const ROLE_GROUPS = {
  operator: { path: operatorGroupPath, dn: operatorGroupDn },
  user: { path: userGroupPath, dn: userGroupDn },
};

const LOGIN_PATH = "/auth/login";
const ACCOUNT_ENTRY = ".NavDrawer .v-navigation-drawer__append .v-list-item:has(.mdi-account)";
const OPEN_MENU = ".menuable__content__active:has(.v-list-item)";
const OPEN_DIALOG = ".v-dialog--active";
const FINISHED_TASK_STATES = new Set(["success", "error", "stopped", "rejected"]);
const TASK_OUTPUT_TAIL_LINES = 30;
const TASK_FAILURE_LINE = /fatal:|FAILED!|ERROR!/;
const TASK_FAILURE_CONTEXT_LINES = 6;
const RBAC_SYNC_CONVERGENCE_MS = 5 * 60_000;
const TASK_RUN_MS = 10 * 60_000;

function onLoginPage(page) {
  return page.url().includes(LOGIN_PATH);
}

async function gotoLogin(page) {
  await gotoOnion(page, `${semaphoreBaseUrl}${LOGIN_PATH}`, { waitUntil: "domcontentloaded" });
}

async function assertAuthenticated(page, label) {
  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(60_000),
      message: `${label}: expected to leave the Semaphore login page`,
    })
    .not.toContain(LOGIN_PATH);
  await expect(
    page.locator("header, nav, .v-navigation-drawer, .v-app-bar").first(),
    `${label}: authenticated Semaphore chrome must be visible`,
  ).toBeVisible({ timeout: resolveTimeout(60_000) });
}

async function fillLocalLogin(page, username, password) {
  const userField = page.locator("#auth-username").first();
  await userField.waitFor({ state: "visible", timeout: resolveTimeout(30_000) });
  await userField.fill(username);
  await page.locator("#auth-password").first().fill(password);
  await page
    .locator('[data-testid="auth-signin"]')
    .first()
    .click({ timeout: resolveTimeout(30_000) })
    .catch(() => page.keyboard.press("Enter"));
}

async function signInViaLocal(page, username, password, label) {
  await gotoLogin(page);
  await fillLocalLogin(page, username, password);
  await assertAuthenticated(page, label);
}

/**
 * Sign the break-glass account in through Semaphore's login API, which keeps
 * accepting local passwords while SEMAPHORE_PASSWORD_LOGIN_DISABLED hides the
 * form, and open the app with the session cookie it sets.
 *
 * Args:
 *   page: the Playwright page whose context receives the session cookie.
 *   username: the break-glass login name.
 *   password: the break-glass password.
 *   label: the persona label the assertion messages name.
 */
async function signInViaBreakglassApi(page, username, password, label) {
  const response = await apiFetchOnion(page.request, `${semaphoreBaseUrl}/api/auth/login`, {
    method: "POST",
    data: { auth: username, password },
    failOnStatusCode: false,
    timeout: resolveTimeout(30_000),
  });
  expect(response.status(), `${label}: Semaphore's login API must accept the break-glass account`).toBe(204);
  await gotoOnion(page, `${semaphoreBaseUrl}/`, { waitUntil: "domcontentloaded" });
  await assertAuthenticated(page, label);
}

async function signInViaLdap(page, username, password, label) {
  await signInViaLocal(page, username, password, label);
}

/**
 * Return the locator of the OIDC provider button on the login page.
 *
 * Args:
 *   page: the Playwright page showing the Semaphore login page.
 */
function oidcButton(page) {
  return page
    .locator("a, button")
    .filter({ hasText: /sign\s*in\s*with|keycloak|single\s*sign|sso/i })
    .first();
}

async function signInViaOidc(page, username, password, label) {
  await gotoLogin(page);

  const button = oidcButton(page);
  await expect(
    button,
    `${label}: the "Sign in with Keycloak" button must render on the Semaphore login page`,
  ).toBeVisible({ timeout: resolveTimeout(30_000) });
  await button.click({ timeout: resolveTimeout(30_000) });

  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(60_000),
      message: `${label}: expected redirect to Keycloak OIDC auth (${oidcIssuerUrl}/protocol/openid-connect/auth)`,
    })
    .toContain(`${oidcIssuerUrl}/protocol/openid-connect/auth`);

  await performKeycloakLoginForm(page, username, password);
  await assertAuthenticated(page, label);
}

/**
 * Open the app's landing page, open the account menu of its navigation drawer
 * and return the open menu.
 *
 * Args:
 *   page: a Playwright page whose context carries a Semaphore session.
 *   label: the persona label the assertion messages name.
 */
async function openAccountMenu(page, label) {
  await gotoOnion(page, `${semaphoreBaseUrl}/`, { waitUntil: "domcontentloaded" });
  const trigger = page.locator(ACCOUNT_ENTRY).first();
  await expect(trigger, `${label}: the Semaphore navigation drawer must show the account entry`).toBeVisible({
    timeout: resolveTimeout(60_000),
  });
  await trigger.click({ timeout: resolveTimeout(30_000) });
  const menu = page.locator(OPEN_MENU).first();
  await expect(menu, `${label}: the account entry must open the account menu`).toBeVisible({
    timeout: resolveTimeout(30_000),
  });
  return menu;
}

/**
 * Click the sign-out entry of an open account menu and wait for the login page.
 *
 * Args:
 *   page: the Playwright page that shows the menu.
 *   menu: the open account menu from `openAccountMenu`.
 *   label: the persona label the assertion messages name.
 */
async function signOutFromMenu(page, menu, label) {
  const signOut = menu
    .locator(".v-list-item")
    .filter({ hasText: /sign\s*out|log\s*out|logout|abmelden/i })
    .or(menu.locator(".v-list-item:has(.mdi-exit-to-app)"))
    .first();
  await expect(signOut, `${label}: the Semaphore account menu must offer a sign-out entry`).toBeVisible({
    timeout: resolveTimeout(30_000),
  });
  await signOut.click({ timeout: resolveTimeout(30_000) });
  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(60_000),
      message: `${label}: expected logged-out landing on the Semaphore login page`,
    })
    .toContain(LOGIN_PATH);
}

/**
 * Sign out through the account menu of the navigation drawer.
 *
 * Args:
 *   page: a Playwright page whose context carries a Semaphore session.
 *   label: the persona label the assertion messages name.
 */
async function logout(page, label) {
  await signOutFromMenu(page, await openAccountMenu(page, label), label);
}

/**
 * Sign in through the primary login path: Keycloak while SSO is on, the
 * LDAP form otherwise.
 *
 * Args:
 *   page: the Playwright page to sign in on.
 *   username: the login name.
 *   password: the password.
 *   label: the persona label the assertion messages name.
 */
async function signInPrimary(page, username, password, label) {
  if (oidcEnabled) {
    await signInViaOidc(page, username, password, label);
    return;
  }
  await signInViaLdap(page, username, password, label);
}

/**
 * Return Semaphore's record of the signed-in account from /api/user.
 *
 * Args:
 *   page: a Playwright page whose context carries the Semaphore session.
 */
async function currentUser(page) {
  const response = await page.request.get(`${semaphoreBaseUrl}/api/user`, {
    failOnStatusCode: false,
    timeout: resolveTimeout(30_000),
  });
  expect(response.status(), "Semaphore must answer /api/user for a signed-in session").toBe(200);
  return response.json();
}

/**
 * Submit the LDAP login form and return the status Semaphore answers the
 * login request with.
 *
 * Args:
 *   page: the Playwright page to drive.
 *   username: the directory login name.
 *   password: the directory password.
 */
async function submitLdapLogin(page, username, password) {
  await gotoLogin(page);
  const loginResponse = page.waitForResponse(
    (response) => response.url().includes("/api/auth/login") && response.request().method() === "POST",
    { timeout: resolveTimeout(60_000) },
  );
  await fillLocalLogin(page, username, password);
  return (await loginResponse).status();
}

/**
 * Run `fn` while biber is a member of the Keycloak group at `groupPath`,
 * removing the membership afterwards only when this call granted it.
 *
 * Args:
 *   browser: the Playwright browser, used for an isolated admin context.
 *   groupPath: the full Keycloak group path, with leading slash.
 *   fn: async body executed while the membership holds.
 */
async function withBiberInGroup(browser, groupPath, fn) {
  const adminOpts = { adminRealm: keycloakAdminRealm, adminClientId: keycloakAdminCliClientId };
  const adminCtx = await browser.newContext({ ignoreHTTPSErrors: true });
  let biberAdded = false;
  try {
    biberAdded = await keycloakAdmin.keycloakAdminAddUserToGroup(
      adminCtx.request,
      keycloakBaseUrl,
      realmName,
      groupPath,
      biberUsername,
      superAdminUsername,
      superAdminPassword,
      adminOpts,
    );
    return await fn();
  } finally {
    if (biberAdded) {
      await keycloakAdmin
        .keycloakRemoveUserFromGroupViaRest(
          adminCtx.request,
          keycloakBaseUrl,
          realmName,
          superAdminUsername,
          superAdminPassword,
          groupPath,
          biberUsername,
          adminOpts,
        )
        .catch((err) => console.warn(`Cleanup removal of biber from ${groupPath} failed: ${err}`));
    }
    await adminCtx.close().catch(() => {});
  }
}

/**
 * Run `fn` while biber is a member of the Semaphore role group `role`.
 *
 * Args:
 *   browser: the Playwright browser, used for an isolated admin context.
 *   role: a key of ROLE_GROUPS, the role from `meta/rbac.yml`.
 *   fn: async body executed while the membership holds.
 */
async function withBiberInRoleGroup(browser, role, fn) {
  const group = ROLE_GROUPS[role];
  if (oidcEnabled) {
    return withBiberInGroup(browser, group.path, fn);
  }
  return withLdapGroupMember(group.dn, biberDn, fn);
}

/**
 * Call the Semaphore API with the session of `page` and return the response.
 *
 * Args:
 *   page: a Playwright page whose context carries a Semaphore session.
 *   method: the HTTP method.
 *   path: the path below `/api`.
 *   data: the JSON body, undefined for none.
 */
async function apiResponse(page, method, path, data) {
  return apiFetchOnion(page.request, `${semaphoreBaseUrl}/api${path}`, {
    method,
    data,
    failOnStatusCode: false,
    timeout: resolveTimeout(30_000),
  });
}

/**
 * Call the Semaphore API with the session of `page`, require a 2xx answer
 * and return its parsed body, null for an empty one.
 *
 * Args:
 *   page: a Playwright page whose context carries a Semaphore session.
 *   method: the HTTP method.
 *   path: the path below `/api`.
 *   data: the JSON body, undefined for none.
 */
async function api(page, method, path, data) {
  const response = await apiResponse(page, method, path, data);
  expect(response.ok(), `${method} /api${path} answered ${response.status()}`).toBe(true);
  const body = await response.text();
  return body ? JSON.parse(body) : null;
}

/**
 * Wait until /api/projects lists the app-control project for the session of
 * `page`, or until it no longer does, and return the project when listed.
 *
 * Args:
 *   page: a Playwright page whose context carries a Semaphore session.
 *   listed: whether the project has to be listed.
 *   label: the persona label the assertion messages name.
 */
async function awaitAppControlProject(page, listed, label) {
  let project;
  await expect
    .poll(
      async () => {
        project = (await api(page, "GET", "/projects")).find((candidate) => candidate.name === projectName);
        return project !== undefined;
      },
      {
        timeout: resolveTimeout(RBAC_SYNC_CONVERGENCE_MS),
        intervals: [15_000],
        message: `${label}: /api/projects must ${listed ? "" : "no longer "}list the "${projectName}" project once the RBAC sync converged`,
      },
    )
    .toBe(listed);
  return project;
}

/**
 * Return the stop and start templates of `applicationId` in the app-control
 * project.
 *
 * Args:
 *   page: a Playwright page whose session may read the project.
 *   projectId: the id of the app-control project.
 *   applicationId: the application the templates act on.
 */
async function appControlTemplates(page, projectId, applicationId) {
  const templates = await api(page, "GET", `/project/${projectId}/templates`);
  const named = (name) => {
    const template = templates.find((candidate) => candidate.name === name);
    expect(
      template,
      `the "${projectName}" project must hold the template "${name}" (holds: ${templates.map((candidate) => candidate.name).join(", ")})`,
    ).toBeTruthy();
    return template;
  };
  return { stop: named(`stop ${applicationId}`), start: named(`start ${applicationId}`) };
}

/**
 * Open `template` from the template list of the project, run it through its
 * run dialog and return the id of the task Semaphore created.
 *
 * Args:
 *   page: a Playwright page whose session may run the template.
 *   projectId: the id of the project holding the template.
 *   template: the template object from the API.
 *   label: the persona label the assertion messages name.
 */
async function runTemplateFromUi(page, projectId, template, label) {
  console.log(`${label}: running "${template.name}" in the runner image tagged ${runnerImageTag}`);
  await gotoOnion(page, `${semaphoreBaseUrl}/project/${projectId}/templates`, { waitUntil: "domcontentloaded" });
  const link = page.locator(".v-data-table").getByRole("link", { name: template.name, exact: true });
  await expect(link, `${label}: the template list must show "${template.name}"`).toBeVisible({
    timeout: resolveTimeout(60_000),
  });
  await link.click({ timeout: resolveTimeout(30_000) });
  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(30_000),
      message: `${label}: "${template.name}" must open its template page`,
    })
    .toMatch(new RegExp(`/project/${projectId}/(?:views/\\d+/)?templates/${template.id}(?:[/?#]|$)`));
  const run = page.locator('[data-testid="template-run"]').first();
  await expect(run, `${label}: the template page must offer running "${template.name}"`).toBeVisible({
    timeout: resolveTimeout(60_000),
  });
  await run.click({ timeout: resolveTimeout(30_000) });
  const dialog = page.locator(OPEN_DIALOG).first();
  await expect(dialog, `${label}: running "${template.name}" must open the run dialog`).toBeVisible({
    timeout: resolveTimeout(30_000),
  });
  const created = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      new URL(response.url()).pathname.endsWith(`/api/project/${projectId}/tasks`),
    { timeout: resolveTimeout(60_000) },
  );
  await dialog.locator('[data-testid="editDialog-save"]').click({ timeout: resolveTimeout(30_000) });
  const response = await created;
  expect(response.ok(), `${label}: Semaphore must accept the run of "${template.name}" (HTTP ${response.status()})`).toBe(
    true,
  );
  return (await response.json()).id;
}

/**
 * Wait until a task finished and require that it succeeded, naming its failure
 * lines and the tail of its output otherwise.
 *
 * Args:
 *   page: a Playwright page whose session may read the task.
 *   projectId: the id of the project holding the task.
 *   taskId: the id of the task.
 *   runMs: the longest the task may run, before timeout scaling.
 *   label: the persona label the assertion messages name.
 */
async function awaitTaskSuccess(page, projectId, taskId, runMs, label) {
  let task;
  await expect
    .poll(
      async () => {
        task = await api(page, "GET", `/project/${projectId}/tasks/${taskId}`);
        return FINISHED_TASK_STATES.has(task.status);
      },
      {
        timeout: resolveTimeout(runMs),
        intervals: [5_000],
        message: `${label}: task ${taskId} must finish`,
      },
    )
    .toBe(true);
  const lines = (await api(page, "GET", `/project/${projectId}/tasks/${taskId}/output`)).map((line) => line.output);
  const failureLines = lines
    .flatMap((line, index) => (TASK_FAILURE_LINE.test(line) ? lines.slice(index, index + TASK_FAILURE_CONTEXT_LINES) : []))
    .join("\n");
  const tail = lines.slice(-TASK_OUTPUT_TAIL_LINES).join("\n");
  expect(
    task.status,
    `${label}: task ${taskId} ended ${task.status}; failure lines:\n${failureLines}\noutput tail:\n${tail}`,
  ).toBe("success");
}

/**
 * Stop a task that has not finished, leaving a finished one untouched.
 *
 * Args:
 *   page: a Playwright page whose session may stop the task.
 *   projectId: the id of the project holding the task.
 *   taskId: the id of the task.
 */
async function stopUnfinishedTask(page, projectId, taskId) {
  const task = await api(page, "GET", `/project/${projectId}/tasks/${taskId}`);
  if (!FINISHED_TASK_STATES.has(task.status)) {
    await api(page, "POST", `/project/${projectId}/tasks/${taskId}/stop`, { force: false });
  }
}

function skipUnlessLdapLogin() {
  skipUnlessServiceEnabled("ldap");
  // nocheck: playwright-sso-ldap-gate -- gates on the ldap login method, which is off under SSO while the ldap service stays on
  test.skip(!loginMethodLdap, "Semaphore's own LDAP login is off; LDAP accounts sign in through Keycloak's federation");
}

async function beforeEach({ page }) {
  await page.setViewportSize({ width: 1440, height: 1100 });
  expect(semaphoreBaseUrl, "SEMAPHORE_BASE_URL must be set").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
  await page.context().clearCookies();
}

module.exports = {
  env: {
    oidcEnabled,
    loginMethodLdap,
    loginMethodNative,
    passwordFormShown,
    oidcIssuerUrl,
    semaphoreBaseUrl,
    adminUsername,
    adminPassword,
    breakglassUsername,
    breakglassPassword,
    biberUsername,
    biberPassword,
    biberEmail,
    canonicalDomain,
    userGroupPath,
    biberDn,
    userGroupDn,
    projectName,
    appControlTargetId,
    appControlTargetUrl,
    pausedLanguage,
    pausedCatalogue,
    pausedContacts,
    dashboardStatusEnabled,
    dashboardBaseUrl,
  },
  LOGIN_PATH,
  RBAC_SYNC_CONVERGENCE_MS,
  TASK_RUN_MS,
  gotoLogin,
  onLoginPage,
  assertAuthenticated,
  currentUser,
  oidcButton,
  signInViaLocal,
  signInViaBreakglassApi,
  signInViaLdap,
  signInViaOidc,
  signInPrimary,
  submitLdapLogin,
  withBiberInGroup,
  withBiberInRoleGroup,
  apiResponse,
  api,
  awaitAppControlProject,
  appControlTemplates,
  runTemplateFromUi,
  awaitTaskSuccess,
  stopUnfinishedTask,
  openAccountMenu,
  signOutFromMenu,
  logout,
  beforeEach,
  skipUnlessLdapLogin,
  skipUnlessServiceDisabled,
  skipUnlessServiceEnabled,
};
