-- Args: allowed ('true' offers the email code sign-in to every account, 'false' to administrator accounts only).
-- Returns one row: the number of tenants that changed.
WITH changed AS (
    UPDATE tenants
    SET is_email_auth_allowed = %(allowed)s::boolean
    WHERE is_email_auth_allowed IS DISTINCT FROM %(allowed)s::boolean
    RETURNING 1
)
SELECT COUNT(*) FROM changed;
