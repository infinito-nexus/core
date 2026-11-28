/**
 * n8n EXTERNAL_HOOK_FILES middleware: trusted-header SSO bridge for n8n
 * Community Edition.
 *
 * n8n CE does not accept the oauth2-proxy edge session as its own — a
 * Keycloak round-trip only clears the `auth_request /oauth2/auth` gate in
 * openresty, leaving the visitor on n8n's native email/password login form.
 * This hook closes that gap: it reads the trusted identity header openresty
 * sets after the auth_request succeeds (see
 * roles/web-app-n8n/templates/proxy.conf.j2), auto-provisions a local n8n
 * user on first sign-in, and issues n8n's own session cookie directly.
 *
 * Security: the header named by N8N_FORWARD_AUTH_HEADER (Remote-Email) is
 * trusted unconditionally, so openresty is the only trust boundary: every
 * front-proxy location blanks a client-supplied copy through
 * roles/sys-svc-proxy/templates/headers/untrusted_identity_strips.conf.j2,
 * and the gated one re-sets it from the oauth2-proxy auth_request response.
 * Anything that reaches n8n's published port without passing openresty can
 * forge it: that port is bound to DOCKER_BIND_HOST (0.0.0.0 under
 * DOCKER_IN_CONTAINER) and, in swarm, published on every node through the
 * routing mesh.
 *
 * Adapted from https://github.com/PavelSozonov/n8n-community-sso (MIT
 * License, Copyright (c) 2025 n8n Community SSO Demo). Differences from
 * upstream:
 *   - first/last name are decoded from X-Forwarded-Access-Token, the
 *     access token nginx bridges through
 *     roles/web-app-keycloak/templates/sso_proxy/following_directives.conf.j2,
 *     instead of the raw client Authorization header (which a client can
 *     set to anything and is not part of this platform's trust chain).
 *   - an account is found by the access token's `sub` in n8n's
 *     auth_identity table (providerType `oidc`), never by email, and the
 *     sign-in is refused unless the token's `email_verified` is true. The
 *     platform administrator (N8N_SSO_OWNER_USERNAME, matched against
 *     X-Forwarded-Preferred-Username) always lands on the instance owner.
 *     An account that holds no auth identity is never reached by SSO; the
 *     deploy binds existing accounts (files/javascript/reconcile/sso_identities.js).
 *   - the upstream demo's `/logout` route is dropped: this platform's own
 *     `/oauth2/sign_out` (oauth2-proxy) and n8n's native `/signout` already
 *     cover logout (see roles/web-app-n8n/files/playwright/_shared.js).
 */

module.exports = {
  n8n: {
    ready: [
      async function ({ app }, config) {
        const { createRequire } = require('module');
        const { dirname, resolve } = require('path');
        const { randomBytes } = require('crypto');
        const n8nRequire = createRequire(require.resolve('n8n'));
        const logger = n8nRequire('@n8n/di').Container.get(n8nRequire('@n8n/backend-common').Logger);

        const headerName = process.env.N8N_FORWARD_AUTH_HEADER;
        if (!headerName) {
          logger.info('N8N_FORWARD_AUTH_HEADER not set; SSO middleware disabled.');
          return;
        }

        logger.info(`SSO middleware initializing with header: ${headerName}`);

        const Layer = createRequire(n8nRequire.resolve('express'))('router/lib/layer');
        const { hash } = n8nRequire('bcryptjs');
        const { issueCookie } = require(resolve(dirname(require.resolve('n8n')), 'auth/jwt'));

        // Trust the proxy for correct X-Forwarded-* handling and rate limiting
        app.set('trust proxy', 1);

        const ignoreAuth = /^\/(assets|healthz|webhook|rest\/oauth2-credential|health)/;
        const cookieName = 'n8n-auth';
        const ownerUsername = process.env.N8N_SSO_OWNER_USERNAME;
        const identityProvider = 'oidc';

        const UserRepo = this.dbCollections.User;
        const AuthIdentityRepo = n8nRequire('@n8n/di').Container.get(n8nRequire('@n8n/db').AuthIdentityRepository);

        const headerValue = (value) => String(Array.isArray(value) ? value[0] : value || '').trim();

        const findSsoUser = async (username, subject) => {
          if (username === ownerUsername) {
            return UserRepo.findOne({ where: { role: { slug: 'global:owner' } }, relations: ['role'] });
          }
          const identity = await AuthIdentityRepo.findOne({ where: { providerId: subject, providerType: identityProvider } });
          if (identity) {
            return UserRepo.findOne({ where: { id: identity.userId }, relations: ['role'] });
          }
          return null;
        };

        const { stack } = app.router;
        const idx = stack.findIndex((l) => l?.name === 'cookieParser');

        const layer = new Layer('/', { strict: false, end: false }, async (req, res, next) => {
          try {
            // Skip if URL matches ignore list
            if (ignoreAuth.test(req.url)) return next();

            // Skip until instance owner setup is complete
            if (!config.get('userManagement.isInstanceOwnerSetUp', false)) return next();

            // Skip if auth cookie already present
            if (req.cookies?.[cookieName]) return next();

            // Read email from the trusted header, and optional given/family
            // names from the trusted access token forwarded alongside it.
            const userEmail = headerValue(req.headers[headerName.toLowerCase()]);
            const username = headerValue(req.headers['x-forwarded-preferred-username']);
            const accessToken = headerValue(req.headers['x-forwarded-access-token']);
            let claims = {};

            if (accessToken) {
              try {
                const parts = accessToken.split('.');
                if (parts.length === 3) {
                  claims = JSON.parse(Buffer.from(parts[1], 'base64').toString());
                }
              } catch (e) {
                logger.debug(`Failed to decode access token: ${e.message}`);
              }
            }

            if (!userEmail || !username) {
              logger.debug(`No ${headerName} or X-Forwarded-Preferred-Username header found, skipping SSO auto-login`);
              return next();
            }

            const subject = headerValue(claims.sub);
            if (claims.email_verified !== true || !subject) {
              logger.info(`SSO auto-login refused for ${username}: the access token carries no subject or no verified email`);
              res.statusCode = 403;
              res.end('Your account has no verified email address.');
              return;
            }

            const userFirstName = headerValue(claims.given_name);
            const userLastName = headerValue(claims.family_name);

            logger.info(`SSO auto-login attempt for ${username}`);

            let user = await findSsoUser(username, subject);

            if (!user && username === ownerUsername) {
              logger.error('The instance owner does not exist; cannot sign the platform administrator in.');
              res.statusCode = 503;
              res.end('The n8n instance owner is not set up yet.');
              return;
            }

            if (!user && (await UserRepo.findOne({ where: { email: userEmail } }))) {
              logger.info(`SSO auto-login refused for ${username}: ${userEmail} belongs to another n8n account`);
              res.statusCode = 409;
              res.end('Your email address belongs to another n8n account.');
              return;
            }

            if (!user) {
              const hashed = await hash(randomBytes(16).toString('hex'), 10);

              const userData = {
                email: userEmail,
                role: { slug: 'global:member' },
                password: hashed,
              };
              if (userFirstName) userData.firstName = userFirstName;
              if (userLastName) userData.lastName = userLastName;

              const created = await UserRepo.createUserWithProject(userData);
              user = created.user;
              await AuthIdentityRepo.save(AuthIdentityRepo.create({ userId: user.id, providerId: subject, providerType: identityProvider }));

              logger.info(`Created new user: ${userEmail} (${userFirstName} ${userLastName}) via SSO`);
            } else {
              let changed = false;
              if (userFirstName && user.firstName !== userFirstName) {
                user.firstName = userFirstName;
                changed = true;
              }
              if (userLastName && user.lastName !== userLastName) {
                user.lastName = userLastName;
                changed = true;
              }
              if (changed) {
                await UserRepo.save(user);
                logger.info(`Updated user: ${userEmail} (${userFirstName} ${userLastName}) via SSO`);
              } else {
                logger.info(`Existing user logged in: ${userEmail} via SSO`);
              }
            }

            if (!user.role) {
              logger.error(`User ${userEmail} has no valid role; cannot issue cookie.`);
              res.statusCode = 401;
              res.end(`User ${userEmail} has no valid role. Ask admin to assign a role.`);
              return;
            }

            issueCookie(res, user);

            req.user = user;
            req.userId = user.id;

            return next();
          } catch (error) {
            logger.error(`SSO middleware error: ${error.message}`);
            return next(error);
          }
        });

        // Insert our middleware right after cookieParser
        stack.splice(idx + 1, 0, layer);
        logger.info('SSO middleware initialized successfully');
      }
    ]
  }
};
