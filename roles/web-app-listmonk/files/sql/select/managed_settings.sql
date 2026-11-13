-- Args: forms (JSON object mapping each prefixed form to its settings key prefix and its sink, whose field names are read as the settings <prefix><field>).
-- Returns one row: a JSON object mapping each prefixed form and the form security to the values Listmonk holds, the OIDC client secret left out.
SELECT COALESCE(
  (
    SELECT jsonb_object_agg(
      form.key,
      COALESCE(
        (
          SELECT jsonb_object_agg(
            substr(settings.key, length(form.value ->> 'prefix') + 1),
            settings.value
          )
          FROM settings
          WHERE settings.key IN (
            SELECT (form.value ->> 'prefix') || field
            FROM jsonb_object_keys(form.value -> 'fields') AS field
          )
        ),
        '{}'::jsonb
      )
    )
    FROM jsonb_each(:'forms'::jsonb) AS form
  ),
  '{}'::jsonb
) || jsonb_build_object(
  'security', COALESCE(
    (
      SELECT value - 'client_secret'
      FROM settings
      WHERE key = 'security.oidc' AND jsonb_typeof(value) = 'object'
    ),
    '{}'::jsonb
  )
);
