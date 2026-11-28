-- Returns one row: the managed columns of the _keycloak OAuth provider as a JSON object without its client secret, or an empty object before the provider exists.
SELECT COALESCE(
    (
        SELECT json_build_object(
            'display_name', display_name,
            'client_id', client_id,
            'authorize_url', authorize_url,
            'token_url', token_url,
            'scope', scope,
            'profile_url', profile_url,
            'json_user_id_path', json_user_id_path,
            'json_user_name_path', json_user_name_path,
            'json_user_email_path', json_user_email_path,
            'is_trusted', is_trusted,
            'status', status
        )::text
        FROM oauth_providers
        WHERE provider = '_keycloak'
          AND tenant_id = (SELECT id FROM tenants LIMIT 1)
    ),
    '{}'
);
