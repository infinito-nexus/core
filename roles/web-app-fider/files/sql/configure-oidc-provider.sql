-- Args: display_name, status (2 lists the provider on the sign-in modal, 1 hides it), client_id, client_secret, authorize_url, token_url, profile_url, scope, json_user_id_path, json_user_name_path, json_user_email_path, is_trusted.

INSERT INTO oauth_providers (
    tenant_id, provider, display_name, status,
    client_id, client_secret,
    authorize_url, token_url, profile_url,
    scope,
    json_user_id_path, json_user_name_path, json_user_email_path,
    logo_bkey, is_trusted
) VALUES (
    (SELECT id FROM tenants LIMIT 1),
    '_keycloak',
    %(display_name)s,
    %(status)s::int,
    %(client_id)s,
    %(client_secret)s,
    %(authorize_url)s,
    %(token_url)s,
    %(profile_url)s,
    %(scope)s,
    %(json_user_id_path)s, %(json_user_name_path)s, %(json_user_email_path)s,
    '', %(is_trusted)s::boolean
)
ON CONFLICT (tenant_id, provider) DO UPDATE SET
    display_name         = EXCLUDED.display_name,
    status               = EXCLUDED.status,
    client_id            = EXCLUDED.client_id,
    client_secret        = EXCLUDED.client_secret,
    authorize_url        = EXCLUDED.authorize_url,
    token_url            = EXCLUDED.token_url,
    profile_url          = EXCLUDED.profile_url,
    scope                = EXCLUDED.scope,
    json_user_id_path    = EXCLUDED.json_user_id_path,
    json_user_name_path  = EXCLUDED.json_user_name_path,
    json_user_email_path = EXCLUDED.json_user_email_path,
    logo_bkey            = EXCLUDED.logo_bkey,
    is_trusted           = EXCLUDED.is_trusted;
