\getenv plugin PEERTUBE_OIDC_PLUGIN
\getenv root_username PEERTUBE_ROOT_USERNAME
\getenv members RBAC_MEMBERS
UPDATE public."user" AS account
SET "pluginAuth" = :'plugin'
WHERE account."pluginAuth" IS NULL
  AND account.username <> :'root_username'
  AND account."lastLoginDate" IS NULL
  AND NOT EXISTS (
    SELECT 1 FROM public."oAuthToken" AS token WHERE token."userId" = account.id
  )
  AND EXISTS (
    SELECT 1
    FROM jsonb_each(:'members'::jsonb) AS grp
    CROSS JOIN jsonb_array_elements(grp.value) AS entry
    WHERE entry->>'username' = account.username
      AND lower(entry->>'email') = lower(account.email)
  )
RETURNING account.username;
