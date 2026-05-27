/**
 * Post-auth app-interaction helpers.
 *
 * Every persona scenario MUST drive a real, role-specific interaction
 * AFTER the auth chain settles — proving the role is not just reachable
 * and authenticated but actually responsive to user input. There is
 * NO generic fallback: a generic "click any visible link" assertion
 * tests nothing role-specific, so this module deliberately refuses to
 * provide one. Each role's spec MUST supply its own `biberInteraction`
 * / `adminInteraction` callback that exercises a meaningful surface
 * (post a message, open a settings tab, browse a content list, ...).
 *
 * `runRoleInteraction` is a thin trampoline: when the spec passes a
 * callback through `runBiberFlow` / `runAdminFlow` opts, the callback
 * runs; when it does not, the helper is a no-op (the persona scenario
 * still asserts auth via the surrounding flow, but the role-specific
 * coverage is left to the spec's own dedicated test blocks).
 *
 * The peer-exchange helper (`runPeerExchangeFlow`) is gated on the
 * role declaring biber↔administrator interaction; its scope is the
 * role-specific spec, not this helper module.
 */

async function runRoleInteraction(page, opts = {}) {
  const { roleInteraction } = opts;
  if (typeof roleInteraction !== "function") return;
  await roleInteraction(page, opts);
}

/**
 * Drive a peer exchange between biber and administrator on roles that
 * support it (peer-to-peer messaging, comment threads, federation
 * round-trips, …). The spec MUST pass a `peerExchange` callback that
 * accepts two pages (biber's, administrator's) plus the credentials
 * read from the env, and the callback drives the role-specific
 * exchange. The helper provides the two browser contexts and tears
 * them down on exit; the role-specific message/payload/assertion
 * lives in the role's own spec.
 */
async function runPeerExchangeFlow(browser, opts) {
  const { peerExchange, biberCreds, adminCreds, env } = opts;
  if (typeof peerExchange !== "function") return;

  const ctxBiber = await browser.newContext({ ignoreHTTPSErrors: true });
  const ctxAdmin = await browser.newContext({ ignoreHTTPSErrors: true });
  const pageBiber = await ctxBiber.newPage();
  const pageAdmin = await ctxAdmin.newPage();
  try {
    await peerExchange({ pageBiber, pageAdmin, biberCreds, adminCreds, env });
  } finally {
    await ctxBiber.close().catch(() => {});
    await ctxAdmin.close().catch(() => {});
  }
}

module.exports = { runRoleInteraction, runPeerExchangeFlow };
