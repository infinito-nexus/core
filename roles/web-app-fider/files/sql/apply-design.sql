-- Args: title (empty keeps the name), bootstrap_name (the name the role bootstrapped the tenant with), css, logo_key, logo_base64 (empty keeps the logo).
-- Returns one row: the number of rows that changed.
WITH tenant AS (
    SELECT id FROM tenants ORDER BY id LIMIT 1
), logo AS (
    INSERT INTO blobs (tenant_id, key, size, content_type, file, created_at, modified_at)
    SELECT tenant.id, %(logo_key)s, octet_length(decode(%(logo_base64)s, 'base64')), 'image/png',
           decode(%(logo_base64)s, 'base64'), NOW(), NOW()
    FROM tenant
    WHERE %(logo_base64)s <> ''
    ON CONFLICT (tenant_id, key) DO UPDATE
        SET size = EXCLUDED.size, file = EXCLUDED.file, modified_at = NOW()
        WHERE blobs.file IS DISTINCT FROM EXCLUDED.file
    RETURNING 1
), desired AS (
    SELECT tenants.id,
           CASE WHEN %(title)s <> '' AND tenants.name = %(bootstrap_name)s
                THEN %(title)s ELSE tenants.name END AS name,
           CASE WHEN tenants.custom_css = '' OR position('--infinito-design-carrier' IN tenants.custom_css) > 0
                THEN %(css)s ELSE tenants.custom_css END AS custom_css,
           CASE WHEN %(logo_base64)s <> '' AND COALESCE(tenants.logo_bkey, '') = ''
                THEN %(logo_key)s ELSE tenants.logo_bkey END AS logo_bkey
    FROM tenants
    JOIN tenant ON tenant.id = tenants.id
), settings AS (
    UPDATE tenants
    SET name = desired.name, custom_css = desired.custom_css, logo_bkey = desired.logo_bkey
    FROM desired
    WHERE tenants.id = desired.id
      AND (tenants.name, tenants.custom_css, tenants.logo_bkey)
          IS DISTINCT FROM (desired.name, desired.custom_css, desired.logo_bkey)
    RETURNING 1
)
SELECT (SELECT COUNT(*) FROM logo) + (SELECT COUNT(*) FROM settings);
