/**
 * TLS-dependent header assertions shared by role specs.
 *
 * HSTS (Strict-Transport-Security) is an HTTPS-only header: per RFC 6797 a
 * user agent MUST ignore it when received over plain HTTP, and OpenResty only
 * emits it on the TLS vhost. On an onion node every domain is served over
 * http:// (onion v3 is the transport auth; there is no public TLS cert for a
 * .onion), so the header is legitimately absent. Gate the assertion on the
 * scheme the app is actually reached over so the same spec passes on both
 * clearnet (TLS) and onion (plaintext) nodes.
 */

const { expect } = require("@playwright/test");

function isTlsBaseUrl(baseUrl) {
  return /^https:/i.test(String(baseUrl || ""));
}

function expectHstsWhenTls(headers, baseUrl, label) {
  if (isTlsBaseUrl(baseUrl)) {
    expect(
      headers["strict-transport-security"],
      `${label} must emit HSTS`,
    ).toBeTruthy();
  } else {
    expect(
      headers["strict-transport-security"],
      `${label} must not emit HSTS over plaintext onion transport`,
    ).toBeFalsy();
  }
}

module.exports = { isTlsBaseUrl, expectHstsWhenTls };
