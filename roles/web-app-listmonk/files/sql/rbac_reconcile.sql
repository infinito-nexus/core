\getenv members RBAC_MEMBERS
\getenv roles LISTMONK_RBAC_ROLES
\getenv administrator LISTMONK_RBAC_ADMINISTRATOR
\getenv protected LISTMONK_RBAC_PROTECTED
\getenv admin_role LISTMONK_RBAC_ADMIN_ROLE
\getenv admin_role_id LISTMONK_RBAC_ADMIN_ROLE_ID
CREATE TEMP TABLE rbac_roles AS
SELECT r.role->>'name' AS name,
       ARRAY(SELECT json_array_elements_text(r.role->'permissions')) AS permissions,
       r.rank
FROM json_array_elements(:'roles'::json) WITH ORDINALITY AS r(role, rank);

INSERT INTO roles (type, name, permissions)
SELECT 'user', w.name, w.permissions
FROM rbac_roles w
WHERE NOT EXISTS (SELECT 1 FROM roles r WHERE r.name = w.name)
RETURNING 'CHANGED role ' || name || ' created';
\set roles_created :ROW_COUNT

UPDATE roles r
SET permissions = w.permissions
FROM rbac_roles w
WHERE r.name = w.name
  AND r.type = 'user'
  AND r.permissions IS DISTINCT FROM w.permissions
RETURNING 'CHANGED role ' || r.name || ' permissions';
\set roles_updated :ROW_COUNT

CREATE TEMP TABLE rbac_wanted AS
SELECT DISTINCT ON (lower(w.email))
       lower(w.username) AS username,
       lower(w.email) AS email,
       CASE WHEN w.role_name = :'admin_role'
            THEN :'admin_role_id'::int
            ELSE (SELECT r.id FROM roles r WHERE r.name = w.role_name AND r.type = 'user')
       END AS role_id
FROM (
  SELECT a.username, a.email, :'admin_role' AS role_name, 0 AS rank
  FROM json_to_record(:'administrator'::json) AS a(username text, email text)
  UNION ALL
  SELECT entry->>'username',
         entry->>'email',
         grp.key,
         CASE WHEN grp.key = :'admin_role'
              THEN 0
              ELSE (SELECT rbac_roles.rank FROM rbac_roles WHERE rbac_roles.name = grp.key)
         END
  FROM json_each(:'members'::json) AS grp
  CROSS JOIN json_array_elements(grp.value) AS entry
) AS w
WHERE length(w.email) > 0
ORDER BY lower(w.email), w.rank;

UPDATE users u
SET user_role_id = w.role_id,
    status = 'enabled'
FROM rbac_wanted w
WHERE lower(u.email) = w.email
  AND u.type = 'user'
  AND (u.user_role_id IS DISTINCT FROM w.role_id OR u.status <> 'enabled')
RETURNING 'CHANGED ' || u.username || ' role=' || w.role_id || ' enabled';
\set users_updated :ROW_COUNT

INSERT INTO users (username, password_login, password, email, name, type, user_role_id, status)
SELECT w.username, false, NULL, w.email, w.username, 'user', w.role_id, 'enabled'
FROM rbac_wanted w
WHERE NOT EXISTS (
  SELECT 1 FROM users u WHERE lower(u.email) = w.email OR lower(u.username) = w.username
)
RETURNING 'CHANGED ' || username || ' created role=' || user_role_id;
\set users_created :ROW_COUNT

UPDATE users u
SET status = 'disabled'
WHERE u.type = 'user'
  AND u.status = 'enabled'
  AND lower(u.email) NOT IN (SELECT email FROM rbac_wanted)
  AND lower(u.username) NOT IN (SELECT lower(p) FROM json_array_elements_text(:'protected'::json) AS p)
RETURNING 'CHANGED ' || u.username || ' disabled';
\set users_disabled :ROW_COUNT

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM rbac_wanted w
    LEFT JOIN users u ON lower(u.email) = w.email AND u.type = 'user'
    WHERE u.id IS NULL OR u.user_role_id IS DISTINCT FROM w.role_id OR u.status <> 'enabled'
  ) THEN
    RAISE EXCEPTION 'a Listmonk RBAC member is not converged';
  END IF;
END
$$;

SELECT 'UNCHANGED' WHERE :roles_created + :roles_updated + :users_updated + :users_created + :users_disabled = 0;
