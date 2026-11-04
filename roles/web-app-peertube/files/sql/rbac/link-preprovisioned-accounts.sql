\getenv plugin PEERTUBE_OIDC_PLUGIN
\getenv root_username PEERTUBE_ROOT_USERNAME
\getenv emails PEERTUBE_RBAC_CREATED
UPDATE public."user"
SET "pluginAuth" = :'plugin'
WHERE "pluginAuth" IS NULL
  AND username <> :'root_username'
  AND lower(email) IN (
    SELECT lower(value) FROM jsonb_array_elements_text(:'emails'::jsonb)
  )
RETURNING username;
