// Native (local-DB) auth surface: register a fresh local account via the
// email/password form and land on an authenticated session.
//
// The federated admin has no local password, so this exercises the native path
// via self-registration. It only runs when registration is available: in the
// default deployment OIDC (Keycloak) is the login path and registration is
// disabled (meta/services.yml `registration_enabled`), so the scenario skips
// when `sso` is enabled. (Password re-login is not asserted: without SMTP the
// new profile is never email-verified, so a fresh-session password login is
// rejected — registration itself is the native-auth signal we can verify.)
exports.register = (shared) => {
  const { test, expect, isServiceEnabled, env, penpotRegister } = shared;

  test("native: register a local account and reach an authenticated session", async ({ page }) => {
    test.skip(
      isServiceEnabled("sso"),
      "native local registration is N/A when OIDC is the login path: registration is disabled and accounts are federated",
    );
    test.setTimeout(120_000);
    expect(env.baseUrl, "PENPOT_BASE_URL must be set").toBeTruthy();

    const email = `pw-native-${Date.now()}@example.test`;
    await penpotRegister(page, "PW Native", email, "PwNative-123!");
  });
};
