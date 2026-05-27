-- Idempotent INSERT for the Fider admin user (bypasses email verification).
-- Inserts a row into `users` if not present, then marks any pending
-- email_verifications row for that email as verified.

INSERT INTO users (name, email, created_at, tenant_id, role, status, avatar_type, avatar_bkey)
SELECT
    %(full_name)s,
    %(email)s,
    NOW(),
    (SELECT id FROM tenants LIMIT 1),
    3, 1, 2, ''
WHERE NOT EXISTS (
    SELECT 1 FROM users
    WHERE email = %(email)s
      AND tenant_id = (SELECT id FROM tenants LIMIT 1)
);
UPDATE email_verifications
   SET verified_at = NOW(),
       user_id = (SELECT id FROM users
                  WHERE email = %(email)s
                    AND tenant_id = (SELECT id FROM tenants LIMIT 1))
WHERE email = %(email)s AND verified_at IS NULL;
