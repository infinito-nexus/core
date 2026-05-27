-- Enable the auth-openid-connect plugin and refresh its settings in
-- place. Caller passes %(settings)s (JSON-encoded plugin settings) as
-- named_args; the ::jsonb cast turns the escaped string literal into a
-- jsonb value at the engine boundary.
UPDATE public.plugin
SET settings    = %(settings)s::jsonb,
    enabled     = TRUE,
    uninstalled = FALSE
WHERE name = 'auth-openid-connect'
  AND (
    settings IS DISTINCT FROM %(settings)s::jsonb
    OR enabled IS DISTINCT FROM TRUE
    OR uninstalled IS DISTINCT FROM FALSE
  );
