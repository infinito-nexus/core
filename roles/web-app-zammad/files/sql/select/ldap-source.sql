SELECT
    jsonb_strip_nulls(
        jsonb_build_object(
            'host', (regexp_match(latest.preferences, '\n:?host: ([^\n]+)'))[1],
            'port', ((regexp_match(latest.preferences, '\n:?port: ([0-9]+)'))[1])::integer
        )
    ) AS stored
FROM (SELECT 1 AS anchor) AS wanted
LEFT JOIN LATERAL (
    SELECT source.preferences
    FROM ldap_sources AS source
    WHERE source.name = %(name)s
    ORDER BY source.id
    LIMIT 1
) AS latest ON TRUE;
