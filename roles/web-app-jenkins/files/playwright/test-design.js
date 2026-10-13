const { test, expect } = require("@playwright/test");

const {
  assertDesignTokens,
  assertLightAndDark,
  assertReadable,
  assertToken,
  captureDesignGallery,
  galleryEnabled,
  tokenValue,
} = require("./design");
const { decodeDotenvQuotedValue, gotoOnion, normalizeBaseUrl, performKeycloakLoginForm } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const base = normalizeBaseUrl(process.env.JENKINS_BASE_URL || "").replace(/\/$/, "");
const oidcIssuerUrl = normalizeBaseUrl(process.env.OIDC_ISSUER_URL || "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);
const ssoEnabled = process.env.SSO_SERVICE_ENABLED === "true";
const ldapEnabled = process.env.LDAP_SERVICE_ENABLED === "true";
const brandingUrl = decodeDotenvQuotedValue(process.env.DESIGN_BRANDING_URL || "");
const faviconUrl = decodeDotenvQuotedValue(process.env.DESIGN_FAVICON_URL || "");
const iconUrl = decodeDotenvQuotedValue(process.env.DESIGN_ICON_URL || "");
const mastheadUrl = decodeDotenvQuotedValue(process.env.DESIGN_MASTHEAD_URL || "");
const title = decodeDotenvQuotedValue(process.env.DESIGN_TITLE || "");

const MODES = ["light", "dark"];
const NO_SIGN_IN_PAGE = "with sso on the oic-auth realm sends /login to Keycloak, so Jenkins never renders its own sign-in page";
const NO_LOCAL_REALM = "with sso or ldap on, casc.yaml selects the oic or ldap realm and holds no local account";
const USERNAME = "#j_username";
const PASSWORD = "#j_password";
const SUBMIT = "button[name='Submit']";
const SAVE = "form[name='config'] button[name='Submit']";
const BRANDING = ".app-sign-in-register__branding";
const HEADER = "#page-header";
const HEADER_LOGO = "#jenkins-head-icon";
const PROJECTS = "#projectstatus";
const PROJECT_ROW = "#projectstatus tbody tr";
const DASHBOARD = "#main-panel .dashboard";
const SECTION = "#main-panel .jenkins-section";
const SHOWCASE = "design-showcase";
const FAILING = "design-failing";
const PIPELINE = "design-pipeline";
const READY = 10_000;

/**
 * Args:
 *   page: Playwright page whose finite animations must have ended.
 */
async function animationsSettled(page) {
  await expect
    .poll(
      () =>
        page.evaluate(() =>
          document
            .getAnimations()
            .some(
              (animation) =>
                animation.playState === "running" && animation.effect?.getComputedTiming().iterations !== Infinity,
            ),
        ),
      { message: "every finite animation of the page must have ended", timeout: resolveTimeout(READY) },
    )
    .toBe(false);
}

function shown(selector) {
  return async (page) => {
    await expect(page.locator(selector).first()).toBeVisible({ timeout: resolveTimeout(READY) });
    await animationsSettled(page);
  };
}

/**
 * Args:
 *   page: Playwright page that shows `selector`.
 *   selector: element whose pseudo-element is read; Jenkins paints buttons and list items on `::before`.
 *   pseudo: pseudo-element, for example `::before`.
 *   property: computed CSS property.
 *   token: design token the value must equal.
 *   label: name of the assertion in the failure message.
 */
async function assertPseudoToken(page, selector, pseudo, property, token, label) {
  const expected = await tokenValue(page, token, property);
  await expect
    .poll(
      () =>
        page
          .locator(selector)
          .first()
          .evaluate((element, [which, cssProperty]) => getComputedStyle(element, which).getPropertyValue(cssProperty), [
            pseudo,
            property,
          ]),
      { message: `${label}: ${selector}${pseudo} ${property} must equal ${token}` },
    )
    .toBe(expected);
}

/**
 * Args:
 *   page: Playwright page whose `selector` paints its fill on `::before`.
 *   selector: control whose text is measured against its own pseudo-element fill.
 *   label: name of the assertion in the failure message.
 *   min: minimal contrast ratio.
 */
async function assertPseudoReadable(page, selector, label, min = 4.5) {
  const ratio = await page
    .locator(selector)
    .first()
    .evaluate((element) => {
      const ctx = document.createElement("canvas").getContext("2d", { willReadFrequently: true });
      const rgb = (value) => {
        ctx.clearRect(0, 0, 1, 1);
        ctx.fillStyle = "#000";
        ctx.fillStyle = value;
        ctx.fillRect(0, 0, 1, 1);
        return Array.from(ctx.getImageData(0, 0, 1, 1).data.slice(0, 3));
      };
      const lum = ([r, g, b]) => {
        const lin = (c) => (c / 255 <= 0.04045 ? c / 255 / 12.92 : ((c / 255 + 0.055) / 1.055) ** 2.4);
        return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
      };
      const fg = lum(rgb(getComputedStyle(element).color));
      const bg = lum(rgb(getComputedStyle(element, "::before").backgroundColor));
      return (Math.max(fg, bg) + 0.05) / (Math.min(fg, bg) + 0.05);
    });
  expect(ratio, `${label}: ${selector} text against its ::before fill reaches ${ratio.toFixed(2)} (needs ${min})`).toBeGreaterThanOrEqual(min);
}

/**
 * Args:
 *   page: Playwright page that ends signed in as the administrator, through Keycloak when sso is on and through the Jenkins form otherwise.
 */
async function signIn(page) {
  if (ssoEnabled) {
    await gotoOnion(page, `${base}/`);
    await expect.poll(() => page.url(), { timeout: resolveTimeout(60_000) }).toContain(`${oidcIssuerUrl}/protocol/openid-connect/auth`);
    await performKeycloakLoginForm(page, adminUsername, adminPassword);
    await expect.poll(() => page.url(), { timeout: resolveTimeout(90_000) }).toContain(base);
    await gotoOnion(page, `${base}/`);
  } else {
    await gotoOnion(page, `${base}/login`);
    await expect(page.locator(USERNAME)).toBeEditable({ timeout: resolveTimeout(60_000) });
    await page.locator(USERNAME).fill(adminUsername);
    await expect(page.locator(PASSWORD)).toBeEditable({ timeout: resolveTimeout(READY) });
    await page.locator(PASSWORD).fill(adminPassword);
    await page.locator(SUBMIT).click();
  }
  await expect(page.locator(HEADER)).toBeVisible({ timeout: resolveTimeout(60_000) });
}

/**
 * Args:
 *   page: signed-in Playwright page on a Jenkins document; the request carries the page's session and crumb.
 *   script: Groovy source for the script console.
 */
async function runGroovy(page, script) {
  return page.evaluate(async (source) => {
    const head = document.head.dataset;
    const response = await fetch("/scriptText", {
      method: "POST",
      headers: { [head.crumbHeader]: head.crumbValue, "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ script: source }).toString(),
    });
    return { status: response.status, text: (await response.text()).trim() };
  }, script);
}

function freestyle(command) {
  return `<?xml version='1.1' encoding='UTF-8'?><project><description>Seeded for the corporate design review.</description><keepDependencies>false</keepDependencies><properties/><scm class="hudson.scm.NullSCM"/><canRoam>true</canRoam><disabled>false</disabled><triggers/><concurrentBuild>false</concurrentBuild><builders><hudson.tasks.Shell><command>${command}</command></hudson.tasks.Shell></builders><publishers/><buildWrappers/></project>`;
}

function pipeline() {
  const stages = ["Build", "Test", "Deploy"].map((stage) => `    stage('${stage}') {\n      steps {\n        echo '${stage}'\n      }\n    }`);
  const script = `pipeline {\n  agent any\n  stages {\n${stages.join("\n")}\n  }\n}`;
  return `<?xml version='1.1' encoding='UTF-8'?><flow-definition plugin="workflow-job"><description>Seeded for the corporate design review.</description><keepDependencies>false</keepDependencies><properties/><definition class="org.jenkinsci.plugins.workflow.cps.CpsFlowDefinition" plugin="workflow-cps"><script>${script}</script><sandbox>true</sandbox></definition><triggers/><disabled>false</disabled></flow-definition>`;
}

/**
 * Args:
 *   page: signed-in Playwright page; three jobs are created or reconfigured until their last build ends with the expected result, through the page's own session and crumb.
 */
async function seedShowcase(page) {
  const jobs = [
    { name: SHOWCASE, config: freestyle("echo 'Design showcase'"), result: "SUCCESS" },
    { name: FAILING, config: freestyle("echo 'Design showcase failure'; exit 1"), result: "FAILURE" },
    { name: PIPELINE, config: pipeline(), result: "SUCCESS" },
  ];
  for (const job of jobs) {
    const status = await page.evaluate(
      async ({ name, config, result }) => {
        const head = document.head.dataset;
        const headers = { [head.crumbHeader]: head.crumbValue };
        const xml = { ...headers, "Content-Type": "application/xml" };
        const existing = await fetch(`/job/${name}/api/json?tree=lastCompletedBuild[result]`, { headers });
        if (existing.status === 404) {
          const created = await fetch(`/createItem?name=${encodeURIComponent(name)}`, { method: "POST", headers: xml, body: config });
          if (!created.ok) return created.status;
        } else {
          if ((await existing.json()).lastCompletedBuild?.result === result) return 200;
          const updated = await fetch(`/job/${name}/config.xml`, { method: "POST", headers: xml, body: config });
          if (!updated.ok) return updated.status;
        }
        const queued = await fetch(`/job/${name}/build`, { method: "POST", headers });
        return queued.status;
      },
      job,
    );
    expect(status, `seeding ${job.name}`).toBeLessThan(400);
  }
  for (const job of jobs) {
    await expect
      .poll(
        () =>
          page.evaluate(async (name) => {
            const response = await fetch(`/job/${name}/api/json?tree=lastCompletedBuild[result]`);
            return response.ok ? (await response.json()).lastCompletedBuild?.result : null;
          }, job.name),
        { message: `${job.name} must end its last build with ${job.result}`, timeout: resolveTimeout(120_000) },
      )
      .toBe(job.result);
  }
}

function signInViews() {
  return [
    { name: "sign-in", url: `${base}/login`, prepare: shown(USERNAME) },
    {
      name: "sign-in-focus",
      url: `${base}/login`,
      prepare: async (page) => {
        await shown(USERNAME)(page);
        await page.locator(USERNAME).focus();
      },
    },
    { name: "sign-in-error", url: `${base}/loginError`, prepare: shown(".app-sign-in-register__error") },
  ];
}

function signedInViews() {
  const view = (name, path, selector) => ({ name, url: `${base}${path}`, prepare: shown(selector) });
  const user = encodeURIComponent(adminUsername.toLowerCase());
  return [
    view("dashboard", "/", DASHBOARD),
    view("build-history", "/view/all/builds", "#main-panel table"),
    view("new-item", "/view/all/newJob", "#add-item-panel #name"),
    view("job", `/job/${SHOWCASE}/`, "#main-panel h1"),
    view("job-failing", `/job/${FAILING}/`, "#main-panel h1"),
    view("job-configure", `/job/${SHOWCASE}/configure`, SAVE),
    view("build", `/job/${SHOWCASE}/lastCompletedBuild/`, "#main-panel h1"),
    view("build-console", `/job/${SHOWCASE}/lastCompletedBuild/console`, "pre.console-output"),
    view("pipeline", `/job/${PIPELINE}/`, "#main-panel h1"),
    view("pipeline-configure", `/job/${PIPELINE}/configure`, SAVE),
    view("manage", "/manage/", SECTION),
    view("configure-system", "/manage/configure", SAVE),
    view("configure-security", "/manage/configureSecurity/", SAVE),
    view("configure-tools", "/manage/configureTools/", SAVE),
    view("plugins-installed", "/manage/pluginManager/installed", "#plugins"),
    view("nodes", "/manage/computer/", "#computers"),
    view("node-built-in", "/manage/computer/(built-in)/", "#main-panel h1"),
    view("credentials", "/manage/credentials/", "#main-panel h1"),
    view("appearance", "/manage/appearance/", "#main-panel h1"),
    view("script-console", "/manage/script", "#main-panel h1"),
    view("log-recorders", "/manage/log/", "#main-panel h1"),
    view("about", "/manage/about/", "#main-panel h1"),
    ...(ssoEnabled ? [] : [view("users", "/manage/securityRealm/", "#people")]),
    view("user-account", `/user/${user}/account/`, SAVE),
    {
      name: "delete-dialog",
      url: `${base}/job/${SHOWCASE}/`,
      prepare: async (page) => {
        await shown("#main-panel h1")(page);
        await page.locator("#tasks a.confirmation-link").first().click();
        await shown("dialog[open]")(page);
        await expect(page.locator("dialog[open]")).toHaveCSS("opacity", "1");
      },
    },
    {
      name: "user-menu",
      url: `${base}/`,
      prepare: async (page) => {
        await shown(DASHBOARD)(page);
        await page.locator("#root-action-UserAction").hover();
        await shown(".tippy-box")(page);
        await expect(page.locator(".tippy-box").first()).toHaveCSS("opacity", "1");
      },
    },
    {
      name: "command-palette",
      url: `${base}/`,
      prepare: async (page) => {
        await shown(DASHBOARD)(page);
        await page.locator("#root-action-SearchAction").click();
        await shown("#command-palette[open]")(page);
        await expect(page.locator("#command-palette[open]")).toHaveCSS("opacity", "1");
      },
    },
  ];
}

test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await signIn(page);
  await assertDesignTokens(page, "Jenkins");
});

test("design: the sign-in page takes surface, primary action, frame and text from the palette", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  test.skip(ssoEnabled, NO_SIGN_IN_PAGE);
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    await gotoOnion(page, `${base}/login`);
    await shown(USERNAME)(page);
    await assertToken(page, "body", "background-color", "--design-surface-1", `sign-in ${mode}`);
    await assertToken(page, "h1", "color", "--design-text", `sign-in ${mode}`);
    await assertToken(page, PASSWORD, "background-color", "--design-surface-2", `sign-in ${mode}`);
    await assertToken(page, PASSWORD, "border-top-color", "--design-border-strong", `sign-in ${mode}`);
    await page.locator(USERNAME).focus();
    await assertToken(page, USERNAME, "border-top-color", "--design-link", `focused sign-in field ${mode}`);
    await assertPseudoToken(page, SUBMIT, "::before", "background-color", "--design-primary", `sign-in ${mode}`);
    await assertToken(page, SUBMIT, "color", "--design-on-primary", `sign-in ${mode}`);
    await assertPseudoReadable(page, SUBMIT, `sign-in ${mode}`);
    await assertPseudoToken(page, BRANDING, "::before", "background-color", "--design-frame", `sign-in branding ${mode}`);
    await page.locator(SUBMIT).hover();
    await assertPseudoToken(page, SUBMIT, "::before", "background-color", "--design-primary-hover", `hovered sign-in ${mode}`);
  }
  await page.emulateMedia({ colorScheme: null });
  await assertLightAndDark(page, "#main-panel", "Jenkins sign-in");
  await assertReadable(page, ["h1", ".app-sign-in-register__form-label"], "Jenkins sign-in");
});

test("design: the signed-in interface takes surfaces, primary action, dividers and text from the palette", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await signIn(page);
  await seedShowcase(page);
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    await gotoOnion(page, `${base}/`);
    await shown(PROJECTS)(page);
    await assertToken(page, "body", "background-color", "--design-surface-1", `dashboard ${mode}`);
    await assertToken(page, "#main-panel", "color", "--design-text", `dashboard ${mode}`);
    await assertToken(page, PROJECTS, "background-color", "--design-surface-3", `job table ${mode}`);
    await assertToken(page, `${PROJECT_ROW} td`, "background-color", "--design-surface-2", `job row ${mode}`);
    await assertToken(page, `${PROJECT_ROW} a.jenkins-table__link`, "color", "--design-link", `job link ${mode}`);
    await gotoOnion(page, `${base}/manage/`);
    await shown(SECTION)(page);
    await assertToken(page, SECTION, "border-top-color", "--design-border", `manage divider ${mode}`);
    await gotoOnion(page, `${base}/job/${SHOWCASE}/configure`);
    await shown(SAVE)(page);
    await assertPseudoToken(page, SAVE, "::before", "background-color", "--design-primary", `save ${mode}`);
    await assertToken(page, SAVE, "color", "--design-on-primary", `save ${mode}`);
    await assertPseudoReadable(page, SAVE, `save ${mode}`);
  }
  await page.emulateMedia({ colorScheme: null });
  await gotoOnion(page, `${base}/`);
  await shown(PROJECTS)(page);
  await assertLightAndDark(page, `${PROJECT_ROW} td`, "Jenkins dashboard");
  await assertReadable(
    page,
    [`${PROJECT_ROW} td`, `${PROJECT_ROW} a.jenkins-table__link`, `${PROJECTS} th`, { selector: "#systemmessage", optional: true }],
    "Jenkins dashboard",
  );
});

test("design: the header and the sign-in page show the generated logo and the configured title", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  test.skip(!mastheadUrl && !title, "logo and title replacement are disabled for this role");
  await signIn(page);
  await gotoOnion(page, `${base}/`);
  await shown(PROJECTS)(page);
  if (title) {
    await expect.poll(() => page.title()).toContain(title);
  }
  if (mastheadUrl) {
    await expect(page.locator(HEADER_LOGO)).toHaveCSS("content", `url("${mastheadUrl}")`);
    const box = await page.locator(HEADER_LOGO).boundingBox();
    expect(box.width, "the header lockup must be wider than high").toBeGreaterThan(box.height);
    await expect(page.locator("link[rel~='icon']").first()).toHaveAttribute("href", faviconUrl);
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(page.locator(HEADER_LOGO)).toHaveCSS("content", `url("${iconUrl}")`);
  }
  if (!ssoEnabled && mastheadUrl) {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.context().clearCookies();
    await gotoOnion(page, `${base}/login`);
    await shown(USERNAME)(page);
    await expect(page.locator(`${BRANDING} img`)).toHaveCSS("content", `url("${brandingUrl}")`);
  }
});

test("administrator: CasC sets the inventory password on the existing local account", async ({ page, browser }) => {
  test.skip(ssoEnabled || ldapEnabled, NO_LOCAL_REALM);
  await signIn(page);
  const scramble = await runGroovy(
    page,
    [
      "def details = hudson.security.HudsonPrivateSecurityRealm.Details",
      `def user = hudson.model.User.getById(${JSON.stringify(adminUsername)}, false)`,
      "def saved = user.getProperty(details)",
      "def scrambled = details.fromPlainPassword(UUID.randomUUID().toString())",
      "user.addProperty(scrambled)",
      "try {",
      "  io.jenkins.plugins.casc.ConfigurationAsCode.get().configure()",
      "} finally {",
      "  if (user.getProperty(details).is(scrambled)) {",
      "    user.addProperty(saved)",
      "    print('kept')",
      "  } else {",
      "    print('reapplied')",
      "  }",
      "}",
    ].join("\n"),
  );
  expect(scramble.status, "the script console must accept the administrator").toBe(200);
  expect(scramble.text, "re-applying casc.yaml must replace a password that differs from the inventory").toBe("reapplied");
  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  try {
    await signIn(await context.newPage());
  } finally {
    await context.close();
  }
});

test("design: gallery of sign-in, dashboard, jobs, builds and administration", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
  test.setTimeout(resolveTimeout(2_400_000));
  let signInFailure = null;
  if (!ssoEnabled) {
    await captureDesignGallery(page, signInViews()).catch((error) => {
      signInFailure = error;
    });
  }
  await signIn(page);
  await seedShowcase(page);
  await captureDesignGallery(page, signedInViews());
  if (signInFailure) throw signInFailure;
});
