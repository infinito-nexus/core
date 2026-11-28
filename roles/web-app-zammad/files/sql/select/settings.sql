SELECT
    jsonb_object_agg(
        setting.name,
        CASE (regexp_match(setting.state_current, '^:?value: (\S+)$', 'n'))[1]
            WHEN 'true' THEN TRUE
            WHEN 'false' THEN FALSE
        END
    ) AS stored
FROM settings AS setting
WHERE setting.name IN (SELECT json_array_elements_text(%(fields)s::json));
