-- Returns one row: whether the first tenant offers the email code sign-in, as a JSON object, or an empty object before the tenant exists.
SELECT COALESCE(
    (
        SELECT json_build_object('is_email_auth_allowed', is_email_auth_allowed)::text
        FROM tenants
        ORDER BY id
        LIMIT 1
    ),
    '{}'
);
