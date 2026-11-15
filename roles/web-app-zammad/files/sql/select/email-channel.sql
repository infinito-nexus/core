SELECT
    jsonb_strip_nulls(
        jsonb_build_object(
            'inbound_host', (regexp_match(inbound.block, '\n    :?host: ([^\n]+)'))[1],
            'inbound_port', ((regexp_match(inbound.block, '\n    :?port: ([0-9]+)'))[1])::integer,
            'outbound_host', (regexp_match(outbound.block, '\n    :?host: ([^\n]+)'))[1],
            'outbound_port', ((regexp_match(outbound.block, '\n    :?port: ([0-9]+)'))[1])::integer
        )
    ) AS stored
FROM (SELECT 1 AS anchor) AS wanted
LEFT JOIN LATERAL (
    SELECT channel.options
    FROM channels AS channel
    INNER JOIN groups AS mail_group ON channel.group_id = mail_group.id
    WHERE channel.area = 'Email::Account' AND mail_group.name = %(group_name)s
    ORDER BY channel.id
    LIMIT 1
) AS latest ON TRUE
LEFT JOIN LATERAL (
    SELECT (regexp_match(latest.options, '\n:?inbound:[^\n]*((?:\n  [^\n]*)*)'))[1] AS block
) AS inbound ON TRUE
LEFT JOIN LATERAL (
    SELECT (regexp_match(latest.options, '\n:?outbound:[^\n]*((?:\n  [^\n]*)*)'))[1] AS block
) AS outbound ON TRUE;
