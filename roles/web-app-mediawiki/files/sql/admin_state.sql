SELECT CASE
    WHEN s.id IS NOT NULL AND s.sysop > 0 THEN 'admin'
    WHEN s.id IS NOT NULL AND s.email_match AND s.confirmed THEN 'not-admin:match'
    WHEN s.id IS NOT NULL AND s.email_match THEN 'not-admin:unconfirmed'
    WHEN s.id IS NOT NULL THEN 'not-admin:mismatch'
    WHEN (
        SELECT COUNT(*) FROM user_groups
        WHERE ug_group = 'sysop' AND (ug_expiry IS NULL OR ug_expiry > DATE_FORMAT(UTC_TIMESTAMP(), '%Y%m%d%H%i%s'))
    ) = 0 THEN 'no-admin'
    WHEN h.holders IS NOT NULL THEN CONCAT('email-held:', h.holders)
    ELSE 'absent'
END AS state
FROM (SELECT 1) AS one
LEFT JOIN (
    SELECT
        user_id AS id,
        (
            SELECT COUNT(*) FROM user_groups
            WHERE
                ug_user = user_id
                AND ug_group = 'sysop' AND (ug_expiry IS NULL OR ug_expiry > DATE_FORMAT(UTC_TIMESTAMP(), '%Y%m%d%H%i%s'))
        ) AS sysop,
        LOWER(CONVERT(user_email USING utf8mb4)) = LOWER(CONVERT(%(email)s USING utf8mb4)) AS email_match,
        user_email_authenticated IS NOT NULL AS confirmed
    FROM user
    WHERE user_name = CAST(
        CONCAT(
            UPPER(LEFT(REPLACE(CONVERT(%(name)s USING utf8mb4), '_', ' '), 1)),
            SUBSTRING(REPLACE(CONVERT(%(name)s USING utf8mb4), '_', ' '), 2)
        ) AS BINARY
    )
) AS s ON TRUE
LEFT JOIN (
    SELECT GROUP_CONCAT(CONVERT(user_name USING utf8mb4) SEPARATOR ', ') AS holders
    FROM user
    WHERE
        LOWER(CONVERT(user_email USING utf8mb4)) = LOWER(CONVERT(%(email)s USING utf8mb4))
        AND user_name <> CAST(
            CONCAT(
                UPPER(LEFT(REPLACE(CONVERT(%(name)s USING utf8mb4), '_', ' '), 1)),
                SUBSTRING(REPLACE(CONVERT(%(name)s USING utf8mb4), '_', ' '), 2)
            ) AS BINARY
        )
) AS h ON TRUE
