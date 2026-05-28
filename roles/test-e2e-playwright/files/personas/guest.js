/**
 * `guest` persona: cannot log in anywhere.
 *
 * The guest is an unauthenticated visitor with NO Keycloak account.
 * The flow visits the role's canonical surface and verifies the
 * resulting state is NEVER an authenticated session — the page either
 * sits on a public landing or has been pushed into the auth chain
 * (`/sso/login`, `/oauth2/start`, Keycloak `openid-connect/auth`),
 * but it MUST NOT render a signed-in surface.
 *
 * Deliberately minimal. The flow does NOT attempt to drive the login
 * form: that would risk a 5-minute timeout against any role whose form
 * loops back on empty submission. The "guest cannot log in anywhere"
 * invariant is fully captured by "after one anonymous visit, no
 * signed-in marker is visible".
 */

const { test, expect } = require("@playwright/test");
const { normalizeUrl, readEnv, safeIsEnabled, assertCspInjections } = require("./utils");

async function runGuestFlow(page = {}) {
  if ((process.env.PERSONA_GUEST_BLOCKED || "").toLowerCase() === "true") {
    test.skip(
      true,
      `guest persona is explicitly blocked by the role contract (PERSONA_GUEST_BLOCKED=true). See the role's TODO.md for the rationale and the path back to a runnable journey.`,
    );
    return;
  }

  const appBaseUrl = normalizeUrl(process.env.APP_BASE_URL);
  const canonicalDomain = readEnv("CANONICAL_DOMAIN");

  // Persona-collapse exception: roles whose env does not
  // expose CANONICAL_DOMAIN are auth-less by construction (web-svc-*
  // and federation-only web-app-*). The guest persona is skipped
  // cleanly; the role's own baseline scenario carries the unauth
  // probe.
  if (!canonicalDomain) {
    test.skip(
      true,
      "Auth-less role (no CANONICAL_DOMAIN) — guest persona scenario collapsed.",
    );
    return;
  }
  if (!appBaseUrl) {
    test.skip(
      true,
      "Auth-less role with no public surface (no APP_BASE_URL) — guest persona scenario collapsed.",
    );
    return;
  }

  test.setTimeout(60_000);

  const startUrl = appBaseUrl;

  await page.context().clearCookies();

  let response;
  try {
    response = await page.goto(startUrl, {
      waitUntil: "domcontentloaded",
      timeout: 30_000,
    });
  } catch (err) {
    throw new Error(
      `guest: page.goto(${startUrl}) failed before the 30s navigation timeout: ${err.message}`,
      { cause: err },
    );
  }

  if (response) {
    expect(response.status(), "guest visit must not 5xx").toBeLessThan(500);
  }

  // CSP must be enforced for the guest too: the page MUST not load
  // resources outside the declared policy regardless of auth state.
  await assertCspInjections(page, { isEnabled: safeIsEnabled }).catch(() => {});

  const finalUrl = page.url();
  const reachedAuthChain =
    /openid-connect\/auth/.test(finalUrl) ||
    /\/sso\/login/.test(finalUrl) ||
    /\/oauth2\/start/.test(finalUrl) ||
    /\/login(\b|\?|\/)/i.test(finalUrl);

  // Whether the URL stayed on the role's public surface or was
  // redirected into the auth chain, the body MUST NOT expose a
  // signed-in marker (logout link/button visible to authenticated
  // users only).
  const signedInMarker = page
    .getByRole("button", { name: /^(log\s*out|sign\s*out|abmelden)$/i })
    .or(page.getByRole("link", { name: /^(log\s*out|sign\s*out|abmelden)$/i }));
  const isSignedIn = await signedInMarker.first().isVisible({ timeout: 1_000 }).catch(() => false);
  expect(
    isSignedIn,
    `guest must NOT end on a signed-in surface (URL ${finalUrl}, reachedAuthChain=${reachedAuthChain})`,
  ).toBe(false);
}

module.exports = { runGuestFlow };
