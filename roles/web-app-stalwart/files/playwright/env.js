const { decodeDotenvQuotedValue } = require("./personas");

const appBaseUrl = decodeDotenvQuotedValue(process.env.APP_BASE_URL || "").replace(/\/+$/, "");
const webmailBaseUrl = decodeDotenvQuotedValue(process.env.WEBMAIL_BASE_URL || "").replace(/\/+$/, "");
const canonicalDomain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN || "");
const oidcIssuerUrl = decodeDotenvQuotedValue(process.env.OIDC_ISSUER_URL || "");
const adminEmail = decodeDotenvQuotedValue(process.env.ADMIN_EMAIL || "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME || "");
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD || "");
const stalwartAdminUsername = decodeDotenvQuotedValue(process.env.STALWART_ADMIN_USERNAME || "");
const stalwartAdminPassword = decodeDotenvQuotedValue(process.env.STALWART_ADMIN_PASSWORD || "");
const biberEmail = decodeDotenvQuotedValue(process.env.BIBER_EMAIL || "");
const biberUsername = decodeDotenvQuotedValue(process.env.BIBER_USERNAME || "");
const biberPassword = decodeDotenvQuotedValue(process.env.BIBER_PASSWORD || "");

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
};
