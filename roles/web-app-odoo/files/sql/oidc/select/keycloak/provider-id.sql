-- Look up the row id of the Keycloak OAuth provider, if registered.
-- Used to decide between INSERT (first install) and UPDATE (re-deploy),
-- and to link Odoo users to the provider.
SELECT id
FROM auth_oauth_provider
WHERE name = 'Keycloak'
LIMIT 1;
