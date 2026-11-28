SELECT
    setting.var,
    setting.value
FROM settings AS setting
WHERE setting.var IN (
    SELECT json_array_elements_text(%(fields)s::json)
)
ORDER BY setting.var;
