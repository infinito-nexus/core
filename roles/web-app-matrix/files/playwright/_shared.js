const { expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { isServiceEnabled, skipUnlessServiceEnabled } = require("./service-gating");
const {
  assertCspResponseHeader,
  decodeDotenvQuotedValue,
  expectNoCspViolations,
  gotoOnion,
  installCspViolationObserver,
  normalizeBaseUrl,
  performKeycloakLoginForm,
  runGuestFlow,
} = require("./personas");

const oidcIssuerUrl = normalizeBaseUrl(process.env.OIDC_ISSUER_URL || "");
const elementBaseUrl = normalizeBaseUrl(process.env.ELEMENT_BASE_URL || "");
const matrixBaseUrl = normalizeBaseUrl(process.env.MATRIX_BASE_URL || "");
const matrixServerName = decodeDotenvQuotedValue(process.env.MATRIX_SERVER_NAME);
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);
const biberUsername = decodeDotenvQuotedValue(process.env.BIBER_USERNAME);
const biberPassword = decodeDotenvQuotedValue(process.env.BIBER_PASSWORD);
const canonicalDomain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN);
const oidcServiceEnabled = isServiceEnabled("sso");

function attachDiagnostics(page) {
  const consoleErrors = [];
  const pageErrors = [];
  const cspRelated = [];
  // Match only the full "Content Security Policy" phrase Chromium emits on
  // real CSP violations. An `|csp` alternative false-positives on random
  // base64/base58 strings (e.g. Matrix event_ids can contain "csP" as a
  // substring) that Element logs verbatim from matrix_sdk_crypto decrypt
  // warnings. The securitypolicyviolation DOM event in
  // installCspViolationObserver is the canonical source anyway.
  page.on("console", (m) => {
    if (m.type() === "error") consoleErrors.push(m.text());
    if (/content security policy/i.test(m.text())) {
      cspRelated.push({ source: "console", text: m.text() });
    }
  });
  page.on("pageerror", (e) => {
    const text = String(e);
    pageErrors.push(text);
    if (/content security policy/i.test(text)) {
      cspRelated.push({ source: "pageerror", text });
    }
  });
  return { consoleErrors, pageErrors, cspRelated };
}

// Matrix Element SSO flow. Element stores the selected homeserver in
// sessionStorage during SSO initiation and reads it back when consuming the
// `?loginToken=…` the homeserver hands it after Keycloak auth. Hitting
// `/_matrix/client/v3/login/sso/redirect/<idp>` directly bypasses that
// sessionStorage write, which causes Element to fail with "your browser has
// forgotten which homeserver you use" when the loginToken returns. Therefore
// SSO must be initiated from Element's own login page so Element sets
// sessionStorage itself before redirecting to Synapse.
async function signInViaElementOidc(page, username, password, personaLabel) {
  const expectedOidcAuthUrl = `${oidcIssuerUrl}/protocol/openid-connect/auth`;

  await gotoOnion(page, `${elementBaseUrl}/#/login`);

  const ssoButton = page
    .locator(
      [
        ".mx_SSOButton",
        "[data-testid='sso-button']",
        "button[aria-label*='SSO' i]",
        "a[href*='/_matrix/client/v3/login/sso/redirect']"
      ].join(", ")
    )
    .first();
  const ssoTextButton = page
    .locator("button, a, div[role='button']")
    .filter({ hasText: /single\s*sign[- ]*on|continue\s+with\s+(sso|oidc|keycloak|openid)|sign\s+in\s+with\s+(sso|oidc|keycloak|openid)/i })
    .first();
  const candidate = (await ssoButton.isVisible({ timeout: resolveTimeout(15_000) }).catch(() => false))
    ? ssoButton
    : ssoTextButton;
  await expect(candidate, `${personaLabel}: Element SSO entry button on #/login must be visible`).toBeVisible({ timeout: resolveTimeout(30_000) });
  await candidate.click();

  await page.waitForURL((u) => u.toString().includes(expectedOidcAuthUrl), {
    timeout: resolveTimeout(120_000)
  });

  await performKeycloakLoginForm(page, username, password);

  // Synapse renders an "Continue to your account" confirmation page after the
  // Keycloak callback, with a "Continue" link pointing at
  // `<elementBaseUrl>/?loginToken=…`. The link must be clicked to hand the
  // token to Element. First-time logins also display a username-selection form
  // asking the user to pick their Matrix localpart before this confirmation.
  const usernameSelectField = page.locator("input[name='username'], input#field-username").first();
  if (await usernameSelectField.isVisible({ timeout: resolveTimeout(5_000) }).catch(() => false)) {
    await usernameSelectField.fill(username);
    const submit = page.locator("button[type='submit'], input[type='submit']").first();
    await submit.click();
  }

  const continueLink = page
    .locator("a, button")
    .filter({ hasText: /^\s*continue\s*$/i })
    .first();
  await expect(continueLink, `${personaLabel}: Synapse SSO confirmation "Continue" link must appear`).toBeVisible({ timeout: resolveTimeout(60_000) });
  await continueLink.click();

  // Element consumes `?loginToken=…` during SPA bootstrap. The token is
  // single-use so we wait until Element has consumed it and navigated to an
  // authenticated SPA route (#/home, #/room/..., #/welcome — NOT #/login).
  // Including #/login in the accepted set would hide a failed token exchange.
  await page.waitForURL((u) => {
    const url = u.toString();
    if (!url.startsWith(elementBaseUrl)) return false;
    if (url.includes("loginToken=")) return false;
    if (url.includes("/_matrix/")) return false;
    if (url.includes(expectedOidcAuthUrl)) return false;
    if (/#\/login(\/|$|\?)/.test(url)) return false;
    if (/#\/welcome/.test(url) || /#\/home/.test(url) || /#\/room/.test(url)) return true;
    if (u.pathname === "/" && (!u.hash || u.hash === "#" || u.hash === "#/")) return true;
    return false;
  }, { timeout: resolveTimeout(120_000) });

  // With `feature_rust_crypto: true`, Element renders a full-screen "Confirm
  // your digital identity" / "Skip verification for now" interstitial on each
  // new-device login after the account has been provisioned. This interstitial
  // appears *asynchronously* once Element's crypto module finishes bootstrap
  // (not immediately on SPA load). We loop: whichever appears first wins —
  // authenticated UI (no interstitial) or Skip button (click, then continue).
  // Element renders the skip button as `<h1><button><img/></button></h1>` —
  // the visible text "Skip verification for now" lives on the heading (or as
  // an accessible name on the button), not inside the button's textContent.
  // Use ARIA role/name so the locator matches via accessibility tree.
  const skipVerificationButton = page.getByRole("button", { name: /skip\s+verification\s+for\s+now/i }).first();
  // Poll for any authenticated-UI signal directly in the DOM / ARIA tree.
  // Using page.evaluate avoids Locator strictness quirks and is orders of
  // magnitude faster than repeated `locator.isVisible()` round-trips.
  async function authenticatedSignalPresent() {
    return await page.evaluate(() => {
      if (document.querySelector(".mx_RoomList, .mx_UserMenu")) return true;
      const byAccessibleName = (roles, nameRegex) => {
        const selector = roles.map(r => `[role="${r}"]`).join(",");
        const nodes = document.querySelectorAll(selector);
        for (const n of nodes) {
          const name = (n.getAttribute("aria-label") || n.textContent || "").trim();
          if (nameRegex.test(name)) return true;
        }
        return false;
      };
      if (byAccessibleName(["button"], /^user menu$/i)) return true;
      if (byAccessibleName(["navigation"], /^room list$/i)) return true;
      if (byAccessibleName(["tree"], /^spaces$/i)) return true;
      const headings = document.querySelectorAll("h1");
      for (const h of headings) {
        if (/^\s*welcome\s+/i.test(h.textContent || "")) return true;
      }
      return false;
    }).catch(() => false);
  }

  // Element shows a non-blocking but pointer-event-capturing "Failed to load
  // service worker" alert in the Playwright browser (no SW support). If we
  // don't dismiss it, the #mx_Dialog_Container background intercepts clicks
  // on SSO / skip buttons and looks identical to the page hanging. It is
  // rendered as role="alert" (not role="dialog"). We both click the OK
  // button AND force-remove the lingering #mx_Dialog_Container so a stale
  // backdrop cannot block subsequent interactions.
  async function dismissServiceWorkerAlert() {
    await page.evaluate(() => {
      const alerts = document.querySelectorAll('[role="alert"], #mx_Dialog_Container');
      for (const a of alerts) {
        if (!/service worker/i.test(a.textContent || "")) continue;
        const btns = a.querySelectorAll("button");
        for (const b of btns) {
          if (/^\s*ok\s*$/i.test(b.textContent || "")) {
            b.click();
          }
        }
      }
      // Belt-and-braces: if a dialog backdrop is still lingering and has no
      // actionable content (i.e. it is only a stale service-worker alert
      // overlay), remove it so it stops eating clicks.
      document.querySelectorAll("#mx_Dialog_Container").forEach((el) => {
        if (/service worker/i.test(el.textContent || "") || !el.querySelector("button, input, textarea")) {
          el.remove();
        }
      });
    }).catch(() => {});
  }

  // Element may cycle through several states after SSO completes:
  // (a) directly to authenticated UI (room list),
  // (b) through the "Confirm your digital identity" / Skip dialog (rust_crypto
  //     on a new device),
  // (c) bounce back to #/login (token race / sync error / transient issue) —
  //     in which case we need to re-trigger SSO from the login page.
  // Poll state every few seconds up to an overall deadline, handling each
  // case, rather than racing individual waits.
  // Handle Synapse's rc_login rate limit. When Element gets
  // `M_LIMIT_EXCEEDED` during SSO token exchange, it shows a modal with a
  // "Try again" button and keeps the user on its own #/login page. The only
  // way forward is to wait out the rate-limit window (Synapse default drains
  // at 0.17/s) and click "Try again". Waiting less just re-triggers the
  // failure; clicking immediately is counterproductive.
  async function retryOnRateLimitDialog() {
    // Match specifically on the `M_LIMIT_EXCEEDED` error code string (which
    // Element includes verbatim in the dialog body). Matching on
    // "couldn't log you in" alone is too loose — Element uses the same
    // phrasing for non-rate-limit SSO errors, and waiting out a 45s cooldown
    // then clicking "Try again" only helps for rc_login exhaustion.
    const rateLimitDialog = page.getByRole("dialog").filter({ hasText: /M_LIMIT_EXCEEDED/ });
    if (!(await rateLimitDialog.isVisible().catch(() => false))) return false;
    // Synapse's default rc_login drains at ~0.17/s (≈6s per slot) with a
    // burst of 3. After the burst is exhausted, recovery of a usable slot
    // requires a few seconds per slot. Wait 45s to leave margin — clicking
    // "Try again" sooner just re-triggers M_LIMIT_EXCEEDED and burns the
    // next burst slot, extending the outage.
    await page.waitForTimeout(resolveTimeout(45_000));
    const tryAgain = rateLimitDialog.getByRole("button", { name: /^try again$/i }).first();
    await tryAgain.click({ timeout: resolveTimeout(5_000) }).catch(() => {});
    return true;
  }

  // Synapse shows an interstitial "Continue to your account" consent page
  // (`/_synapse/client/sso/redirect/confirm`) on first SSO login for a given
  // account/client pair. The only way forward is a "Continue" link that
  // carries the `?loginToken=` callback URL. Element never renders this page
  // itself — it lives on the Synapse domain — so auth signals will never
  // appear here.
  //
  // Important: if we click "Continue" and Element's subsequent /login call
  // hits Synapse's `rc_login` burst, Element silently re-triggers SSO, which
  // dumps us back on the consent page with a fresh loginToken. Spamming
  // "Continue" each poll iteration burns rc_login slots and turns into an
  // unrecoverable loop. Rate-limit the click to one attempt per ≥30s so
  // rc_login has time to drain between retries.
  let lastConsentClickAt = 0;
  async function passSynapseConsentPage() {
    const heading = page.getByRole("heading", { name: /continue to your account/i });
    if (!(await heading.isVisible().catch(() => false))) return false;
    const now = Date.now();
    if (now - lastConsentClickAt < 30_000) return true;
    // Synapse's consent template historically used an `<a>` link but now
    // ships a `<button>` as the primary action. Match both via role-based
    // lookup AND a DOM-level fallback so the handler keeps working across
    // Synapse template revisions. Using `a, button` with a text filter is
    // more robust than `getByRole("link"|"button")` alone because Synapse
    // sometimes emits a native submit without an accessible name match.
    const continueAction = page
      .locator("a[href*='loginToken=']")
      .or(page.locator("a, button, input[type='submit']").filter({ hasText: /^\s*continue\s*$/i }))
      .first();
    const clickResult = await continueAction
      .click({ timeout: resolveTimeout(10_000) })
      .then(() => "ok")
      .catch((e) => e.message || "click-failed");
    // Only throttle subsequent attempts when the click actually landed.
    // A failed click (locator missed, overlay intercepted, etc.) must not
    // burn the 30s cooldown — otherwise the whole state deadline can
    // expire without ever advancing.
    if (clickResult === "ok") lastConsentClickAt = now;
    return true;
  }

  // 360s (6 minutes) covers the worst case: Synapse rc_login drains at
  // 0.17/s with 3 burst slots, and Element's consent ↔ M_LIMIT_EXCEEDED
  // ping-pong can cost ~75s per cycle (30s consent cool-down + 45s rate
  // limit cool-down). 240s wasn't enough when rc_login was already drained
  // by prior tests in the same spec run.
  const stateDeadline = Date.now() + 360_000;
  while (Date.now() < stateDeadline) {
    await dismissServiceWorkerAlert();
    if (await authenticatedSignalPresent()) break;
    if (await passSynapseConsentPage()) continue;
    if (await retryOnRateLimitDialog()) continue;
    if (await skipVerificationButton.isVisible().catch(() => false)) {
      await skipVerificationButton.click({ timeout: resolveTimeout(5_000) }).catch(() => {});
      // Element may show a secondary confirm dialog for the skip choice.
      // MUST NOT click "Reset identity" — that destroys the device identity
      // and logs the user back out to #/login.
      const confirmSkip = page
        .getByRole("button", { name: /^\s*(skip(\s+anyway)?|i'?ll\s+verify\s+later|continue)\s*$/i })
        .first();
      await confirmSkip.waitFor({ state: "visible", timeout: resolveTimeout(5_000) }).catch(() => {});
      if (await confirmSkip.isVisible().catch(() => false)) {
        await confirmSkip.click({ timeout: resolveTimeout(5_000) }).catch(() => {});
      }
      await page.waitForTimeout(resolveTimeout(2_000));
      continue;
    }
    // If Element has bounced back to its own #/login page AND no auth signal
    // is yet present, re-trigger SSO.
    if (/#\/login(\/|$|\?)/.test(page.url())) {
      const ssoRetry = page
        .locator(
          [
            ".mx_SSOButton",
            "[data-testid='sso-button']",
            "a[href*='/_matrix/client/v3/login/sso/redirect']"
          ].join(", ")
        )
        .or(page.getByRole("button", { name: /continue\s+with\s+sso|single\s*sign[- ]*on/i }))
        .first();
      if (await ssoRetry.isVisible().catch(() => false)) {
        // Short click timeout: if the click is blocked (e.g. by a stale
        // backdrop), we want to fall back to the next poll iteration quickly
        // rather than burning the entire test budget on click-retry.
        await ssoRetry.click({ timeout: resolveTimeout(5_000) }).catch(() => {});
        await page.waitForURL((u) => !/#\/login(\/|$|\?)/.test(u.toString()), { timeout: resolveTimeout(30_000) }).catch(() => {});
      }
    }
    await page.waitForTimeout(resolveTimeout(2_000));
  }

  // Final gate: poll the DOM a few more times. If any of our signals show
  // up, we're authenticated. Otherwise, fail with a descriptive message.
  await expect
    .poll(authenticatedSignalPresent, {
      timeout: resolveTimeout(60_000),
      message: `${personaLabel}: authenticated Element UI (user menu / room list / welcome) must render`
    })
    .toBe(true);
}

// Native password / LDAP-backed login on Element's #/login form (m.login.password).
// Used when OIDC is disabled on the Synapse homeserver. Synapse may back the
// password verification with native users or an `ldap_auth_provider` —
// indistinguishable from Element's side. Skip-verification + service-worker
// dismissal mirror the OIDC path; Synapse SSO consent does not apply.
async function signInViaElementPassword(page, username, password, personaLabel) {
  await gotoOnion(page, `${elementBaseUrl}/#/login`);

  const userField = page
    .locator('input[name="username"], #mx_LoginForm_username, input[name="mxid"], input[data-testid="login_field_mx_id"]')
    .first();
  await expect(userField, `${personaLabel}: Element password login username field must appear`).toBeVisible({ timeout: resolveTimeout(30_000) });
  await userField.fill(username);

  const pwField = page
    .locator('input[name="password"], #mx_LoginForm_password, input[type="password"]')
    .first();
  await pwField.fill(password);

  const submitBtn = page
    .locator('.mx_Login_submit, button[type="submit"], [data-testid="login-submit-button"]')
    .first();
  await submitBtn.click();

  const skipBtn = page.getByRole("button", { name: /skip\s+verification\s+for\s+now/i }).first();
  async function authenticatedSignalPresent() {
    return await page.evaluate(() => {
      if (document.querySelector(".mx_RoomList, .mx_UserMenu")) return true;
      const byAccessibleName = (roles, nameRegex) => {
        const selector = roles.map(r => `[role="${r}"]`).join(",");
        for (const n of document.querySelectorAll(selector)) {
          const name = (n.getAttribute("aria-label") || n.textContent || "").trim();
          if (nameRegex.test(name)) return true;
        }
        return false;
      };
      if (byAccessibleName(["button"], /^user menu$/i)) return true;
      if (byAccessibleName(["navigation"], /^room list$/i)) return true;
      if (byAccessibleName(["tree"], /^spaces$/i)) return true;
      for (const h of document.querySelectorAll("h1")) {
        if (/^\s*welcome\s+/i.test(h.textContent || "")) return true;
      }
      return false;
    }).catch(() => false);
  }
  async function credentialRejectionMessage() {
    return await page.evaluate(() => {
      const sel = ".mx_Login_error, .mx_Login_field_error, [role='alert']";
      for (const n of document.querySelectorAll(sel)) {
        const t = (n.textContent || "").trim();
        if (/invalid|incorrect|forbidden|unauthorized/i.test(t)) return t;
      }
      return null;
    }).catch(() => null);
  }

  const deadline = Date.now() + 180_000;
  while (Date.now() < deadline) {
    if (await authenticatedSignalPresent()) break;
    const rejection = await credentialRejectionMessage();
    if (rejection) {
      throw new Error(`${personaLabel}: Element rejected credentials: "${rejection}"`);
    }
    if (await skipBtn.isVisible().catch(() => false)) {
      await skipBtn.click({ timeout: resolveTimeout(5_000) }).catch(() => {});
      const confirmSkip = page
        .getByRole("button", { name: /^\s*(skip(\s+anyway)?|i'?ll\s+verify\s+later|continue)\s*$/i })
        .first();
      await confirmSkip.waitFor({ state: "visible", timeout: resolveTimeout(5_000) }).catch(() => {});
      if (await confirmSkip.isVisible().catch(() => false)) {
        await confirmSkip.click({ timeout: resolveTimeout(5_000) }).catch(() => {});
      }
      await page.waitForTimeout(resolveTimeout(2_000));
      continue;
    }
    await page.waitForTimeout(resolveTimeout(2_000));
  }

  await expect
    .poll(authenticatedSignalPresent, {
      timeout: resolveTimeout(60_000),
      message: `${personaLabel}: authenticated Element UI (user menu / room list / welcome) must render after password auth`
    })
    .toBe(true);
}

// Auth-mode dispatcher: pick OIDC when Keycloak is wired up for this
// matrix deployment, fall back to native/LDAP password auth otherwise.
async function signInViaElement(page, username, password, personaLabel) {
  if (oidcServiceEnabled) {
    return signInViaElementOidc(page, username, password, personaLabel);
  }
  return signInViaElementPassword(page, username, password, personaLabel);
}

async function beforeEach({ page }) {
  await page.setViewportSize({ width: 1440, height: 1100 });
  expect(oidcIssuerUrl, "OIDC_ISSUER_URL must be set").toBeTruthy();
  expect(elementBaseUrl, "ELEMENT_BASE_URL must be set").toBeTruthy();
  expect(matrixBaseUrl, "MATRIX_BASE_URL must be set").toBeTruthy();
  expect(matrixServerName, "MATRIX_SERVER_NAME must be set").toBeTruthy();
  expect(adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();
  expect(adminPassword, "ADMIN_PASSWORD must be set").toBeTruthy();
  expect(biberUsername, "BIBER_USERNAME must be set").toBeTruthy();
  expect(biberPassword, "BIBER_PASSWORD must be set").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
  await page.context().clearCookies();
  await installCspViolationObserver(page);
}

module.exports = {
  env: {
    oidcIssuerUrl,
    elementBaseUrl,
    matrixBaseUrl,
    matrixServerName,
    adminUsername,
    adminPassword,
    biberUsername,
    biberPassword,
    canonicalDomain,
    oidcServiceEnabled,
  },
  skipUnlessServiceEnabled,
  attachDiagnostics,
  assertCspResponseHeader,
  expectNoCspViolations,
  installCspViolationObserver,
  runGuestFlow,
  signInViaElementOidc,
  signInViaElementPassword,
  signInViaElement,
  beforeEach,
};
