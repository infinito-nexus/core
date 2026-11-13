SELECT jsonb_object_agg(managed.key, managed.value) AS stored
FROM (
    SELECT setting.*
    FROM application_settings AS setting
    ORDER BY setting.id DESC
    LIMIT 1
) AS latest
CROSS JOIN LATERAL jsonb_each(to_jsonb(latest)) AS managed (key, value)
WHERE managed.key IN (
    SELECT json_array_elements_text(%(fields)s::json)
);
