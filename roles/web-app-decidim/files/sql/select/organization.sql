SELECT
    jsonb_strip_nulls(
        jsonb_build_object(
            'host', organization.host,
            'users_registration_mode',
            CASE organization.users_registration_mode::text
                WHEN '0' THEN 'enabled'
                WHEN '1' THEN 'existing'
                WHEN '2' THEN 'disabled'
                ELSE organization.users_registration_mode::text
            END,
            'omniauth_settings_openid_connect_enabled',
            CASE
                WHEN
                    jsonb_typeof(
                        to_jsonb(organization.omniauth_settings)
                        -> 'omniauth_settings_openid_connect_enabled'
                    ) = 'boolean'
                    THEN to_jsonb(organization.omniauth_settings)
                    -> 'omniauth_settings_openid_connect_enabled'
            END
        )
    ) AS stored
FROM (SELECT 1 AS anchor) AS wanted
LEFT JOIN LATERAL (
    SELECT candidate.*
    FROM decidim_organizations AS candidate
    ORDER BY candidate.id
    LIMIT 1
) AS organization ON TRUE;
