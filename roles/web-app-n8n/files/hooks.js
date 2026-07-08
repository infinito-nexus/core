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
 * trusted unconditionally. This is only safe because any client-supplied
 * copy of it is blanked by
 * roles/sys-svc-proxy/templates/headers/untrusted_identity_strips.conf.j2
 * before openresty re-sets it from the oauth2-proxy auth_request response,
 * and n8n's published port is bound to the host's loopback interface
 * (DOCKER_BIND_HOST), so only openresty on the same host can reach it
 * directly — external clients cannot bypass the proxy to forge the header.
 *
 * Adapted from https://github.com/PavelSozonov/n8n-community-sso (MIT
 * License, Copyright (c) 2025 n8n Community SSO Demo). Differences from
 * upstream:
 *   - first/last name are decoded from X-Forwarded-Access-Token, the
 *     access token nginx bridges through
 *     roles/web-app-keycloak/templates/sso_proxy/following_directives.conf.j2,
 *     instead of the raw client Authorization header (which a client can
 *     set to anything and is not part of this platform's trust chain).
 *   - the upstream demo's `/logout` route is dropped: this platform's own
 *     `/oauth2/sign_out` (oauth2-proxy) and n8n's native `/signout` already
 *     cover logout (see roles/web-app-n8n/files/playwright/_shared.js).
 */

module.exports = {
  n8n: {
    ready: [
      async function ({ app }, config) {
        const headerName = process.env.N8N_FORWARD_AUTH_HEADER;
        if (!headerName) {
          this.logger?.info('N8N_FORWARD_AUTH_HEADER not set; SSO middleware disabled.');
          return;
        }

        this.logger?.info(`SSO middleware initializing with header: ${headerName}`);

        const Layer = require('router/lib/layer');
        const { dirname, resolve } = require('path');
        const { randomBytes } = require('crypto');
        const { hash } = require('bcryptjs');
        const { issueCookie } = require(resolve(dirname(require.resolve('n8n')), 'auth/jwt'));

        // Trust the proxy for correct X-Forwarded-* handling and rate limiting
        app.set('trust proxy', 1);

        const ignoreAuth = /^\/(assets|healthz|webhook|rest\/oauth2-credential|health)/;
        const cookieName = 'n8n-auth';

        const UserRepo = this.dbCollections.User;

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
            const emailHeader = req.headers[headerName.toLowerCase()];
            const accessToken = req.headers['x-forwarded-access-token'] || '';
            let firstName = '';
            let lastName = '';

            if (accessToken) {
              try {
                const parts = String(accessToken).split('.');
                if (parts.length === 3) {
                  const payload = JSON.parse(Buffer.from(parts[1], 'base64').toString());
                  firstName = payload.given_name || '';
                  lastName = payload.family_name || '';
                  this.logger?.debug(`Extracted from access token: firstName="${firstName}", lastName="${lastName}"`);
                }
              } catch (e) {
                this.logger?.debug(`Failed to decode access token: ${e.message}`);
              }
            }

            // If the forward-auth header with email is missing — do nothing
            if (!emailHeader) {
              this.logger?.debug(`No ${headerName} header found, skipping SSO auto-login`);
              return next();
            }

            const userEmail = Array.isArray(emailHeader) ? emailHeader[0] : String(emailHeader).trim();
            const userFirstName = Array.isArray(firstName) ? firstName[0] : String(firstName).trim();
            const userLastName = Array.isArray(lastName) ? lastName[0] : String(lastName).trim();

            if (!userEmail) {
              this.logger?.debug(`Empty ${headerName} header, skipping SSO auto-login`);
              return next();
            }

            this.logger?.info(`SSO auto-login attempt for email: ${userEmail}`);

            // 1) Try to fetch the user (n8n 1.95.3 stores 'role' as a plain string column)
            let user = await UserRepo.findOne({
              where: { email: userEmail },
            });

            // 2) If not found — create the user (with 'global:member' role) and a project
            if (!user) {
              const hashed = await hash(randomBytes(16).toString('hex'), 10);

              const userData = {
                email: userEmail,
                role: 'global:member', // string-based role is valid for createUserWithProject
                password: hashed,
              };
              if (userFirstName) userData.firstName = userFirstName;
              if (userLastName) userData.lastName = userLastName;

              const created = await UserRepo.createUserWithProject(userData);
              user = created.user;

              this.logger?.info(`Created new user: ${userEmail} (${userFirstName} ${userLastName}) via SSO`);
            } else {
              // 3) Update first/last name if they changed upstream
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
                this.logger?.info(`Updated user: ${userEmail} (${userFirstName} ${userLastName}) via SSO`);
              } else {
                this.logger?.info(`Existing user logged in: ${userEmail} via SSO`);
              }
            }

            // 4) Ensure 'user.role' exists (plain string column, e.g. 'global:member')
            if (!user.role) {
              this.logger?.error(`User ${userEmail} has no valid role; cannot issue cookie.`);
              res.statusCode = 401;
              res.end(`User ${userEmail} has no valid role. Ask admin to assign a role.`);
              return;
            }

            // 5) Issue n8n auth cookie
            issueCookie(res, user);

            // 6) Attach context for downstream middleware/routes
            req.user = user;
            req.userId = user.id;

            return next();
          } catch (error) {
            this.logger?.error(`SSO middleware error: ${error.message}`);
            return next(error);
          }
        });

        // Insert our middleware right after cookieParser
        stack.splice(idx + 1, 0, layer);
        this.logger?.info('SSO middleware initialized successfully');
      }
    ]
  }
};
