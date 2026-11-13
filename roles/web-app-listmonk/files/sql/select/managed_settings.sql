-- Args: forms (JSON object mapping each prefixed form to its settings key prefix and its sink, whose field names are read as the settings <prefix><field>).
-- Returns one row: a JSON object mapping each prefixed form, the form security and the form captcha to the values Listmonk holds, the OIDC client secret and the hCaptcha key and secret left out.
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
  ),
  'captcha', COALESCE(
    (
      SELECT jsonb_build_object('enabled', value -> 'hcaptcha' -> 'enabled')
      FROM settings
      WHERE key = 'security.captcha' AND jsonb_typeof(value -> 'hcaptcha') = 'object'
    ),
    '{}'::jsonb
  )
);
