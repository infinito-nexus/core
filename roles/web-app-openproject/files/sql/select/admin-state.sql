SELECT
    account.id AS account_id,
    account.admin AS account_admin,
    account.status AS account_status,
    account.force_password_change AS account_force_password_change,
    account.ldap_auth_source_id AS account_ldap_auth_source_id,
    latest_password.id AS password_id,
    md5(latest_password.hashed_password) AS password_digest,
    ldap_source.id AS ldap_source_id,
    stored_settings.state AS settings_state,
    seeded_admin.state AS seeded_admin_state
FROM (
    SELECT
        %(login)s AS wanted_login,
        %(ldap_name)s AS wanted_ldap_name
) AS wanted
LEFT JOIN users AS account
    ON
        account.type = 'User'
        AND wanted.wanted_login = account.login
LEFT JOIN LATERAL (
    SELECT
        candidate.id,
        candidate.hashed_password
    FROM user_passwords AS candidate
    WHERE candidate.user_id = account.id
    ORDER BY candidate.id DESC
    LIMIT 1
) AS latest_password ON TRUE
LEFT JOIN ldap_auth_sources AS ldap_source
    ON wanted.wanted_ldap_name = ldap_source.name
CROSS JOIN LATERAL (
    SELECT
        string_agg(
            concat(setting.name, '=', md5(setting.value)),
            ',' ORDER BY setting.name, setting.id
        ) AS state
    FROM settings AS setting
    WHERE setting.name IN (
        SELECT json_array_elements_text(%(settings)s::json)
    )
) AS stored_settings
CROSS JOIN LATERAL (
    SELECT
        string_agg(
            concat(seeded.id, '=', seeded.status),
            ',' ORDER BY seeded.id
        ) AS state
    FROM users AS seeded
    WHERE
        seeded.type = 'User'
        AND seeded.login = 'admin'
) AS seeded_admin
ORDER BY account_id, ldap_source_id;
