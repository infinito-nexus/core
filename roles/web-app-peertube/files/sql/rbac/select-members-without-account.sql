\getenv members PEERTUBE_RBAC_RANKED
SELECT COALESCE(jsonb_agg(member ORDER BY member->>'username'), '[]'::jsonb)
FROM jsonb_array_elements(:'members'::jsonb) AS member
WHERE NOT EXISTS (
  SELECT 1
  FROM public."user" AS account
  WHERE lower(account.email) = lower(member->>'email')
     OR account.username = member->>'username'
);
