const { resolveTimeout } = require("./timeouts");

/**
 * Args:
 *   locator: Playwright page or frame locator on a Fider page that shows the header "Sign in" button; the call ends on the redirect to the identity provider.
 */
async function clickFiderSsoButton(locator) {
  const signInLink = locator
    .getByRole("button", { name: /sign in/i })
    .or(locator.getByRole("link", { name: /sign in/i }));

  await signInLink.first().waitFor({ state: "visible", timeout: resolveTimeout(30_000) });
  await signInLink.first().click();

  const ssoButton = locator.getByRole("link", { name: /continue with/i });

  await ssoButton.first().waitFor({ state: "visible", timeout: resolveTimeout(15_000) });
  // Fider keeps aria-disabled on the provider link while the modal renders, so the click is forced.
  await ssoButton.first().click({ force: true, timeout: resolveTimeout(30_000) });
}

module.exports = { clickFiderSsoButton };
