SELECT
    coalesce((
        SELECT format_type(attribute.atttypid, attribute.atttypmod)
        FROM pg_catalog.pg_attribute AS attribute
        WHERE
            attribute.attrelid = to_regclass('u')
            AND attribute.attname = 'v'
            AND NOT attribute.attisdropped
    ), 'absent');
