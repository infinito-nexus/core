const { expect } = require("@playwright/test");

/**
 * Args:
 *   page: the page that just completed a login.
 *   timeout: milliseconds to wait, already resolved for the target.
 *   message: what the caller is waiting for, shown when the wait expires.
 */
async function awaitSession(page, timeout, message) {
  await expect
    .poll(
      () =>
        page.evaluate(() =>
          Object.keys(localStorage).some((name) => /user-auth$/.test(name)),
        ),
      { timeout, message },
    )
    .toBe(true);
}

module.exports = { awaitSession };
