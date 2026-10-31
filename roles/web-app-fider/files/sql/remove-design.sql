-- Args: title (the name apply-design.sql wrote), bootstrap_name (the name the role bootstrapped the tenant with), logo_key.
-- Returns one row: the number of rows that changed.
WITH tenant AS (
    SELECT id FROM tenants ORDER BY id LIMIT 1
), desired AS (
    SELECT tenants.id,
           CASE WHEN tenants.name = %(title)s THEN %(bootstrap_name)s ELSE tenants.name END AS name,
           CASE WHEN position('--infinito-design-carrier' IN tenants.custom_css) > 0
                THEN '' ELSE tenants.custom_css END AS custom_css,
           CASE WHEN tenants.logo_bkey = %(logo_key)s THEN '' ELSE tenants.logo_bkey END AS logo_bkey
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
), logo AS (
    DELETE FROM blobs USING tenant
    WHERE blobs.tenant_id = tenant.id AND blobs.key = %(logo_key)s
    RETURNING 1
)
SELECT (SELECT COUNT(*) FROM settings) + (SELECT COUNT(*) FROM logo);
