-- Args: prefix (the settings key prefix of the general form), general (JSON array of the general form fields, each stored as the setting <prefix><field>).
-- Returns one row: a JSON object mapping the forms general and security to the values Listmonk holds, the OIDC client secret left out.
SELECT jsonb_build_object(
  'general', COALESCE(
    (
      SELECT jsonb_object_agg(substr(key, length(:'prefix') + 1), value)
      FROM settings
      WHERE key IN (
        SELECT :'prefix' || field
        FROM jsonb_array_elements_text(:'general'::jsonb) AS field
      )
    ),
    '{}'::jsonb
  ),
  'security', COALESCE(
    (
      SELECT value - 'client_secret'
      FROM settings
      WHERE key = 'security.oidc' AND jsonb_typeof(value) = 'object'
    ),
    '{}'::jsonb
  )
);
