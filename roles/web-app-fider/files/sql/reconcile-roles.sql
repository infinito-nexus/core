-- Args: RBAC_MEMBERS (JSON {role: [{username, email, name}]}), FIDER_RBAC_ROLE_IDS (JSON {role: Fider role id}, its visitor entry for every other account), FIDER_RBAC_BOOTSTRAP_EMAIL (the administrator create-admin-user.sql converges).
-- Returns one CHANGED row per created or re-roled account, else UNCHANGED.
\getenv members RBAC_MEMBERS
\getenv role_ids FIDER_RBAC_ROLE_IDS
\getenv bootstrap_email FIDER_RBAC_BOOTSTRAP_EMAIL
WITH tenant AS (
    SELECT id FROM tenants ORDER BY id LIMIT 1
), member AS (
    SELECT DISTINCT ON (lower(entry->>'email'))
           lower(entry->>'email') AS email,
           entry->>'username' AS username,
           (:'role_ids'::jsonb->>grp.key)::integer AS role
    FROM jsonb_each(:'members'::jsonb) AS grp
    CROSS JOIN jsonb_array_elements(grp.value) AS entry
    WHERE COALESCE(entry->>'email', '') <> ''
    ORDER BY lower(entry->>'email'), (:'role_ids'::jsonb->>grp.key)::integer DESC
), created AS (
    INSERT INTO users (name, email, created_at, tenant_id, role, status, avatar_type, avatar_bkey)
    SELECT member.username, member.email, NOW(), tenant.id, member.role, 1, 2, ''
    FROM member CROSS JOIN tenant
    WHERE member.email <> lower(:'bootstrap_email')
      AND NOT EXISTS (
          SELECT 1 FROM users
          WHERE users.tenant_id = tenant.id AND lower(users.email) = member.email
      )
    RETURNING email, role
), desired AS (
    SELECT users.id,
           COALESCE(
               (SELECT member.role FROM member WHERE member.email = lower(users.email)),
               (:'role_ids'::jsonb->>'visitor')::integer
           ) AS role
    FROM users
    JOIN tenant ON tenant.id = users.tenant_id
    WHERE lower(users.email) <> lower(:'bootstrap_email')
), updated AS (
    UPDATE users
    SET role = desired.role
    FROM desired
    WHERE users.id = desired.id
      AND users.role IS DISTINCT FROM desired.role
    RETURNING users.email, users.role
)
SELECT 'CHANGED ' || email || ' created role=' || role FROM created
UNION ALL
SELECT 'CHANGED ' || email || ' role=' || role FROM updated
UNION ALL
SELECT 'UNCHANGED' WHERE NOT EXISTS (SELECT 1 FROM created) AND NOT EXISTS (SELECT 1 FROM updated);
