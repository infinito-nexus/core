/**
 * Trusted-header SSO bridge for Postmarks.
 *
 * Postmarks core has no OIDC/SSO login: the only authenticated identity is
 * "the owner", established by a single `req.session.loggedIn = true` boolean
 * that the upstream `login()` sets when the posted password matches ADMIN_KEY.
 * In Infinito.Nexus, Postmarks sits behind an oauth2-proxy that authenticates
 * the visitor against Keycloak (OIDC, or LDAP federated through Keycloak) and
 * forwards the resolved identity to this upstream as request headers. This
 * Express middleware turns that trusted header into the owner session.
 *
 * Security: the identity header is trusted unconditionally. This is only safe
 * because Postmarks is reachable exclusively through the oauth2-proxy, which
 * overwrites the header on every request, and the application port is bound to
 * 127.0.0.1. The bridge activates only when PROXY_HEADER_SSO is truthy (wired
 * by the role's env template behind the oauth2 SSO flavor) and is otherwise a
 * transparent pass-through.
 *
 * Only the `X-Forwarded-*` headers nginx overwrites are read; the
 * `X-Auth-Request-*`/`Remote-User` variants are deliberately excluded so a
 * client cannot inject an identity nginx did not set. Postmarks has no user
 * record, so the proxied username/email are not mapped to any app field; they
 * serve solely as proof-of-identity to flip the single `loggedIn` boolean.
 */

const TRUE_VALUES = new Set(['true', '1', 'yes', 'on']);

const USERNAME_HEADERS = ['x-forwarded-preferred-username', 'x-forwarded-user'];
const EMAIL_HEADERS = ['x-forwarded-email'];
const GROUP_HEADERS = ['x-forwarded-groups'];

function ssoEnabled() {
  return TRUE_VALUES.has(String(process.env.PROXY_HEADER_SSO || '').toLowerCase());
}

function firstHeader(req, names) {
  for (const name of names) {
    const value = req.get(name);
    if (value && String(value).trim()) {
      return String(value).trim();
    }
  }
  return null;
}

function splitGroups(raw) {
  if (!raw) {
    return [];
  }
  return String(raw)
    .split(',')
    .flatMap((chunk) => chunk.split(/\s+/))
    .filter(Boolean);
}

function groupMatches(left, right) {
  const l = (left || '').trim();
  const r = (right || '').trim();
  return l === r || l.replace(/^\/+/, '') === r.replace(/^\/+/, '');
}

function isAdmin(groups) {
  const adminGroup = String(process.env.PROXY_HEADER_SSO_ADMIN_GROUP || '').trim();
  return Boolean(adminGroup) && groups.some((group) => groupMatches(group, adminGroup));
}

function proxyHeaderSso(req, res, next) {
  if (!ssoEnabled() || !req.session) {
    return next();
  }

  const username = firstHeader(req, USERNAME_HEADERS);
  const email = firstHeader(req, EMAIL_HEADERS);
  if (!username && !email) {
    return next();
  }

  const adminGroup = String(process.env.PROXY_HEADER_SSO_ADMIN_GROUP || '').trim();
  if (adminGroup && !isAdmin(splitGroups(firstHeader(req, GROUP_HEADERS)))) {
    return next();
  }

  req.session.loggedIn = true;
  req.session.ssoUser = username || email;
  return next();
}

export default proxyHeaderSso;
