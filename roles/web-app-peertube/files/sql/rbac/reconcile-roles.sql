\getenv members RBAC_MEMBERS
\getenv role_ids PEERTUBE_RBAC_ROLE_IDS
\getenv plugin PEERTUBE_OIDC_PLUGIN
WITH member AS (
  SELECT lower(entry->>'email') AS email,
         entry->>'username' AS username,
         (:'role_ids'::jsonb->>grp.key)::integer AS role
  FROM jsonb_each(:'members'::jsonb) AS grp
  CROSS JOIN jsonb_array_elements(grp.value) AS entry
  WHERE COALESCE(entry->>'email', '') <> ''
),
desired AS (
  SELECT account.id,
         COALESCE(
           (
             SELECT min(member.role)
             FROM member
             WHERE member.email = lower(account.email)
                OR member.username = account.username
           ),
           (:'role_ids'::jsonb->>'user')::integer
         ) AS role
  FROM public."user" AS account
  WHERE account."pluginAuth" = :'plugin'
),
updated AS (
  UPDATE public."user" AS account
  SET role = desired.role
  FROM desired
  WHERE account.id = desired.id
    AND account.role IS DISTINCT FROM desired.role
  RETURNING account.username, account.role
)
SELECT 'CHANGED ' || username || ' role=' || role FROM updated
UNION ALL
SELECT 'UNCHANGED' WHERE NOT EXISTS (SELECT 1 FROM updated);
