\getenv members RBAC_MEMBERS
\getenv kept SEMAPHORE_RBAC_KEPT
\getenv project SEMAPHORE_RBAC_PROJECT
\getenv deploy_project SEMAPHORE_RBAC_DEPLOY_PROJECT
WITH administrator AS (
  SELECT DISTINCT ON (lower(entry->>'username'))
         entry->>'username' AS username,
         entry->>'email' AS email,
         COALESCE(NULLIF(entry->>'name', ''), entry->>'username') AS name
  FROM jsonb_array_elements(:'members'::jsonb->'administrator') AS entry
  WHERE COALESCE(entry->>'username', '') <> ''
    AND COALESCE(entry->>'email', '') <> ''
  ORDER BY lower(entry->>'username')
)
INSERT INTO public."user" (created, username, name, email, password, admin, external)
SELECT now(), administrator.username, administrator.name, administrator.email, '', TRUE, TRUE
FROM administrator
WHERE NOT EXISTS (
  SELECT 1
  FROM public."user" AS account
  WHERE lower(account.username) = lower(administrator.username)
     OR lower(account.email) = lower(administrator.email)
)
ON CONFLICT DO NOTHING
RETURNING 'CHANGED ' || username || ' created';
\set created_changes :ROW_COUNT

WITH operator AS (
  SELECT DISTINCT ON (lower(entry->>'username'))
         entry->>'username' AS username,
         entry->>'email' AS email,
         COALESCE(NULLIF(entry->>'name', ''), entry->>'username') AS name
  FROM jsonb_array_elements(:'members'::jsonb->'operator') AS entry
  WHERE COALESCE(entry->>'username', '') <> ''
    AND COALESCE(entry->>'email', '') <> ''
  ORDER BY lower(entry->>'username')
)
INSERT INTO public."user" (created, username, name, email, password, admin, external)
SELECT now(), operator.username, operator.name, operator.email, '', FALSE, TRUE
FROM operator
WHERE NOT EXISTS (
  SELECT 1
  FROM public."user" AS account
  WHERE lower(account.username) = lower(operator.username)
     OR lower(account.email) = lower(operator.email)
)
ON CONFLICT DO NOTHING
RETURNING 'CHANGED ' || username || ' created';
\set operator_created_changes :ROW_COUNT

WITH administrator AS (
  SELECT lower(entry->>'username') AS username,
         lower(entry->>'email') AS email
  FROM jsonb_array_elements(:'members'::jsonb->'administrator') AS entry
),
kept AS (
  SELECT lower(login) AS username
  FROM jsonb_array_elements_text(:'kept'::jsonb) AS login
),
desired AS (
  SELECT account.id,
         lower(account.username) IN (SELECT username FROM kept) AS kept,
         EXISTS (
           SELECT 1
           FROM administrator
           WHERE administrator.username = lower(account.username)
              OR (administrator.email <> '' AND administrator.email = lower(account.email))
         ) AS admin
  FROM public."user" AS account
)
UPDATE public."user" AS account
SET admin = desired.admin
FROM desired
WHERE account.id = desired.id
  AND account.admin IS DISTINCT FROM desired.admin
  AND (desired.admin OR NOT desired.kept)
RETURNING 'CHANGED ' || account.username || ' admin=' || account.admin;
\set admin_changes :ROW_COUNT

WITH member AS (
  SELECT DISTINCT ON (lower(entry->>'username'))
         lower(entry->>'username') AS username,
         NULLIF(entry->>'email', '') AS email,
         NULLIF(entry->>'name', '') AS name
  FROM jsonb_each(:'members'::jsonb) AS grp
  CROSS JOIN jsonb_array_elements(grp.value) AS entry
  ORDER BY lower(entry->>'username'),
           COALESCE(entry->>'name', '') = '',
           COALESCE(entry->>'email', '') = ''
),
desired AS (
  SELECT account.id,
         CASE
           WHEN member.email IS NULL THEN account.email
           WHEN EXISTS (
             SELECT 1
             FROM public."user" AS other
             WHERE other.id <> account.id
               AND lower(other.email) = lower(member.email)
           ) THEN account.email
           ELSE member.email
         END AS email,
         COALESCE(member.name, account.name) AS name
  FROM public."user" AS account
  JOIN member ON member.username = lower(account.username)
  WHERE account.external
)
UPDATE public."user" AS account
SET email = desired.email,
    name = desired.name
FROM desired
WHERE account.id = desired.id
  AND (account.email IS DISTINCT FROM desired.email OR account.name IS DISTINCT FROM desired.name)
RETURNING 'CHANGED ' || account.username || ' profile';
\set profile_changes :ROW_COUNT

WITH operator AS (
  SELECT lower(entry->>'username') AS username,
         lower(COALESCE(entry->>'email', '')) AS email
  FROM jsonb_array_elements(:'members'::jsonb->'operator') AS entry
  WHERE COALESCE(entry->>'username', '') <> ''
),
target AS (
  SELECT id
  FROM public.project
  WHERE name = :'project'
),
member AS (
  SELECT account.id
  FROM public."user" AS account
  WHERE EXISTS (
    SELECT 1
    FROM operator
    WHERE operator.username = lower(account.username)
       OR (operator.email <> '' AND operator.email = lower(account.email))
  )
)
INSERT INTO public.project__user (project_id, user_id, role)
SELECT target.id, member.id, 'task_runner'
FROM target
CROSS JOIN member
WHERE NOT EXISTS (
  SELECT 1
  FROM public.project__user AS granted
  WHERE granted.project_id = target.id
    AND granted.user_id = member.id
)
RETURNING 'CHANGED user ' || user_id || ' task_runner granted';
\set granted_changes :ROW_COUNT

WITH operator AS (
  SELECT lower(entry->>'username') AS username,
         lower(COALESCE(entry->>'email', '')) AS email
  FROM jsonb_array_elements(:'members'::jsonb->'operator') AS entry
  WHERE COALESCE(entry->>'username', '') <> ''
),
target AS (
  SELECT id
  FROM public.project
  WHERE name = :'project'
),
member AS (
  SELECT account.id
  FROM public."user" AS account
  WHERE EXISTS (
    SELECT 1
    FROM operator
    WHERE operator.username = lower(account.username)
       OR (operator.email <> '' AND operator.email = lower(account.email))
  )
)
UPDATE public.project__user AS granted
SET role = 'task_runner'
FROM target, member
WHERE granted.project_id = target.id
  AND granted.user_id = member.id
  AND granted.role = 'guest'
RETURNING 'CHANGED user ' || granted.user_id || ' task_runner promoted';
\set promoted_changes :ROW_COUNT

WITH operator AS (
  SELECT lower(entry->>'username') AS username,
         lower(COALESCE(entry->>'email', '')) AS email
  FROM jsonb_array_elements(:'members'::jsonb->'operator') AS entry
  WHERE COALESCE(entry->>'username', '') <> ''
),
target AS (
  SELECT id
  FROM public.project
  WHERE name = :'project'
),
member AS (
  SELECT account.id
  FROM public."user" AS account
  WHERE EXISTS (
    SELECT 1
    FROM operator
    WHERE operator.username = lower(account.username)
       OR (operator.email <> '' AND operator.email = lower(account.email))
  )
)
DELETE FROM public.project__user AS granted
USING target
WHERE granted.project_id = target.id
  AND granted.role = 'task_runner'
  AND granted.user_id NOT IN (SELECT id FROM member)
RETURNING 'CHANGED user ' || granted.user_id || ' task_runner revoked';
\set revoked_changes :ROW_COUNT

WITH deploy AS (
  SELECT id
  FROM public.project
  WHERE name = :'deploy_project'
)
INSERT INTO public.project__user (project_id, user_id, role)
SELECT deploy.id, account.id, 'owner'
FROM deploy
CROSS JOIN public."user" AS account
WHERE account.admin
  AND NOT EXISTS (
    SELECT 1
    FROM public.project__user AS granted
    WHERE granted.project_id = deploy.id
      AND granted.user_id = account.id
  )
RETURNING 'CHANGED user ' || user_id || ' deploy owner granted';
\set deploy_granted_changes :ROW_COUNT

WITH deploy AS (
  SELECT id
  FROM public.project
  WHERE name = :'deploy_project'
)
DELETE FROM public.project__user AS granted
USING deploy, public."user" AS account
WHERE granted.project_id = deploy.id
  AND granted.user_id = account.id
  AND NOT account.admin
RETURNING 'CHANGED user ' || granted.user_id || ' deploy membership revoked';
\set deploy_revoked_changes :ROW_COUNT

WITH member AS (
  SELECT lower(entry->>'username') AS username,
         lower(entry->>'email') AS email
  FROM jsonb_each(:'members'::jsonb) AS grp
  CROSS JOIN jsonb_array_elements(grp.value) AS entry
),
kept AS (
  SELECT lower(login) AS username
  FROM jsonb_array_elements_text(:'kept'::jsonb) AS login
),
outsider AS (
  SELECT account.id, account.username
  FROM public."user" AS account
  WHERE account.external
    AND lower(account.username) NOT IN (SELECT username FROM kept)
    AND NOT EXISTS (
      SELECT 1
      FROM member
      WHERE member.username = lower(account.username)
         OR (member.email <> '' AND member.email = lower(account.email))
    )
),
expired_session AS (
  UPDATE public.session AS login_session
  SET expired = TRUE
  FROM outsider
  WHERE login_session.user_id = outsider.id
    AND NOT login_session.expired
  RETURNING login_session.user_id
),
expired_token AS (
  UPDATE public.user__token AS api_token
  SET expired = TRUE
  FROM outsider
  WHERE api_token.user_id = outsider.id
    AND NOT api_token.expired
  RETURNING api_token.user_id
)
SELECT 'CHANGED ' || outsider.username || ' signed out'
FROM outsider
WHERE outsider.id IN (SELECT user_id FROM expired_session UNION SELECT user_id FROM expired_token)
ORDER BY outsider.username;
\set expired_changes :ROW_COUNT

SELECT 'UNCHANGED'
WHERE :created_changes + :operator_created_changes + :admin_changes + :profile_changes
    + :granted_changes + :promoted_changes + :revoked_changes
    + :deploy_granted_changes + :deploy_revoked_changes + :expired_changes = 0;
