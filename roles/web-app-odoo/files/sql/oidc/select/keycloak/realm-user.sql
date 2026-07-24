-- Look up a username in the Keycloak realm DB to confirm the user
-- exists before linking the matching Odoo user to the Keycloak OAuth
-- provider. Caller passes %(realm)s and %(admin)s as named_args.
SELECT username
FROM user_entity
WHERE realm_id = (SELECT id FROM realm WHERE name = %(realm)s)
  AND username = %(admin)s;
