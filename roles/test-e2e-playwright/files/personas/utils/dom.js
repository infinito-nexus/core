/**
 * Small DOM / locator utilities shared by Playwright specs.
 *
 *   `isVisible(locator)`
 *     Resolve to `true` iff `locator.first()` is currently visible.
 *     Swallows the strict-mode / detached-element errors so callers
 *     can treat the result as a plain truthy check.
 *
 *   `waitForFrameUrl(iframeLocator, matcher, timeout, errorMessage)`
 *     Poll the URL of the frame embedded by `iframeLocator` until it
 *     contains `matcher`. Used by specs that drive a flow inside a
 *     fullscreen iframe (dashboard wraps services this way) and need
 *     to assert the iframe URL settled on a known endpoint.
 *
 *   `findFirstVisibleCandidate(candidates)`
 *     Walk a list of `{ locator, … }` candidates and return the first
 *     one whose `locator.first()` is visible. Returns `null` when none
 *     are visible. The returned object preserves caller-supplied
 *     metadata fields (e.g. role-specific labels) and rebinds `locator`
 *     to the resolved single-element locator.
 *
 *   `escapeRegex(value)`
 *     Escape every character that has special meaning in a JavaScript
 *     regular-expression source string. Suitable for embedding a raw
 *     string into a `new RegExp(...)` or `getByRole({ name: new RegExp(`^${escapeRegex(s)}$`) })`.
 */

const { expect } = require("@playwright/test");

async function isVisible(locator) {
  return locator.first().isVisible().catch(() => false);
}

async function waitForFrameUrl(iframeLocator, matcher, timeout, errorMessage) {
  await expect
    .poll(
      async () => {
        const iframeHandle = await iframeLocator.elementHandle();
        const frame = iframeHandle ? await iframeHandle.contentFrame() : null;
        return frame ? frame.url() : "";
      },
      {
        timeout,
        message: errorMessage,
      }
    )
    .toContain(matcher);
}

async function findFirstVisibleCandidate(candidates) {
  for (const candidate of candidates) {
    const locator = candidate.locator.first();
    if (await locator.isVisible().catch(() => false)) {
      return { ...candidate, locator };
    }
  }
  return null;
}

function escapeRegex(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

module.exports = {
  isVisible,
  waitForFrameUrl,
  findFirstVisibleCandidate,
  escapeRegex,
};
