const { requireDotenvValue } = require("./personas");

const appBaseUrl = requireDotenvValue(process.env.APP_BASE_URL, "APP_BASE_URL").replace(/\/+$/, "");
const webmailBaseUrl = requireDotenvValue(process.env.WEBMAIL_BASE_URL, "WEBMAIL_BASE_URL").replace(/\/+$/, "");
const canonicalDomain = requireDotenvValue(process.env.CANONICAL_DOMAIN, "CANONICAL_DOMAIN");
const oidcIssuerUrl = requireDotenvValue(process.env.OIDC_ISSUER_URL, "OIDC_ISSUER_URL");
const adminEmail = requireDotenvValue(process.env.ADMIN_EMAIL, "ADMIN_EMAIL");
const adminUsername = requireDotenvValue(process.env.ADMIN_USERNAME, "ADMIN_USERNAME");
const adminPassword = requireDotenvValue(process.env.ADMIN_PASSWORD, "ADMIN_PASSWORD");
const stalwartAdminUsername = requireDotenvValue(process.env.STALWART_ADMIN_USERNAME, "STALWART_ADMIN_USERNAME");
const stalwartAdminPassword = requireDotenvValue(process.env.STALWART_ADMIN_PASSWORD, "STALWART_ADMIN_PASSWORD");
const biberEmail = requireDotenvValue(process.env.BIBER_EMAIL, "BIBER_EMAIL");
const biberUsername = requireDotenvValue(process.env.BIBER_USERNAME, "BIBER_USERNAME");
const biberPassword = requireDotenvValue(process.env.BIBER_PASSWORD, "BIBER_PASSWORD");
const mapachePassword = requireDotenvValue(process.env.MAPACHE_PASSWORD, "MAPACHE_PASSWORD");

const expectedOidcAuthUrl = `${oidcIssuerUrl.replace(/\/$/, "")}/protocol/openid-connect/auth`;

module.exports = {
  appBaseUrl,
  webmailBaseUrl,
  canonicalDomain,
  oidcIssuerUrl,
  expectedOidcAuthUrl,
  adminEmail,
  adminUsername,
  adminPassword,
  stalwartAdminUsername,
  stalwartAdminPassword,
  biberEmail,
  biberUsername,
  biberPassword,
  mapachePassword,
};
