-- Args: names (JSON object mapping each team form to the name of its team).
-- Returns one row: each form whose team exists in the first organizer by slug, mapped to the managed fields that team holds, as a JSON object.
SELECT COALESCE(
    json_object_agg(
        forms.key,
        json_build_object(
            'all_events', team.all_events,
            'all_event_permissions', team.all_event_permissions,
            'limit_event_permissions', team.limit_event_permissions,
            'all_organizer_permissions', team.all_organizer_permissions,
            'limit_organizer_permissions', team.limit_organizer_permissions
        )
    )::text,
    '{}'
)
FROM json_each_text(%(names)s::json) AS forms
JOIN pretixbase_team AS team ON team.name = forms.value
WHERE team.organizer_id = (
    SELECT id FROM pretixbase_organizer ORDER BY slug LIMIT 1
);
