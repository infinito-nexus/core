SELECT
    'account' AS kind,
    u.lower_name AS a,
    u.type AS b,
    u.is_admin AS c,
    u.max_repo_creation AS d,
    u.login_source AS e,
    (SELECT COUNT(*) FROM external_login_user AS x WHERE x.user_id = u.id) AS f
FROM `user` AS u
WHERE u.lower_name = %(store)s AND u.type <> 1
UNION ALL
SELECT
    'organization',
    o.lower_name,
    o.visibility,
    '',
    '',
    '',
    ''
FROM `user` AS o
WHERE o.lower_name = %(organization)s AND o.type = 1
UNION ALL
SELECT
    'owned_repository',
    r.lower_name,
    '',
    '',
    '',
    '',
    ''
FROM repository AS r
INNER JOIN `user` AS u ON r.owner_id = u.id
WHERE u.lower_name = %(store)s AND u.type <> 1
UNION ALL
SELECT
    'membership',
    o.lower_name,
    '',
    '',
    '',
    '',
    ''
FROM org_user AS ou
INNER JOIN `user` AS o ON ou.org_id = o.id
INNER JOIN `user` AS u ON ou.uid = u.id
WHERE u.lower_name = %(store)s AND u.type <> 1
UNION ALL
SELECT
    'team_membership',
    o.lower_name,
    t.lower_name,
    '',
    '',
    '',
    ''
FROM team_user AS tu
INNER JOIN team AS t ON tu.team_id = t.id
INNER JOIN `user` AS o ON t.org_id = o.id
INNER JOIN `user` AS u ON tu.uid = u.id
WHERE u.lower_name = %(store)s AND u.type <> 1
UNION ALL
SELECT
    'team',
    t.lower_name,
    t.authorize,
    t.includes_all_repositories,
    t.can_create_org_repo,
    '',
    ''
FROM team AS t
INNER JOIN `user` AS o ON t.org_id = o.id
WHERE o.lower_name = %(organization)s AND o.type = 1
UNION ALL
SELECT
    'team_unit',
    t.lower_name,
    tn.type,
    tn.access_mode,
    '',
    '',
    ''
FROM team_unit AS tn
INNER JOIN team AS t ON tn.team_id = t.id
INNER JOIN `user` AS o ON t.org_id = o.id
WHERE o.lower_name = %(organization)s AND o.type = 1
UNION ALL
SELECT
    'team_member',
    t.lower_name,
    m.lower_name,
    '',
    '',
    '',
    ''
FROM team_user AS tm
INNER JOIN team AS t ON tm.team_id = t.id
INNER JOIN `user` AS o ON t.org_id = o.id
INNER JOIN `user` AS m ON tm.uid = m.id
WHERE o.lower_name = %(organization)s AND o.type = 1
UNION ALL
SELECT
    'repository',
    r.lower_name,
    '',
    '',
    '',
    '',
    ''
FROM repository AS r
INNER JOIN `user` AS o ON r.owner_id = o.id
WHERE o.lower_name = %(organization)s AND o.type = 1
UNION ALL
SELECT
    'deploy_key',
    r.lower_name,
    k.name,
    k.mode,
    '',
    '',
    ''
FROM deploy_key AS k
INNER JOIN repository AS r ON k.repo_id = r.id
INNER JOIN `user` AS o ON r.owner_id = o.id
WHERE o.lower_name = %(organization)s AND o.type = 1
UNION ALL
SELECT
    'collaborator',
    r.lower_name,
    c.lower_name,
    cb.mode,
    '',
    '',
    ''
FROM collaboration AS cb
INNER JOIN repository AS r ON cb.repo_id = r.id
INNER JOIN `user` AS o ON r.owner_id = o.id
INNER JOIN `user` AS c ON cb.user_id = c.id
WHERE o.lower_name = %(organization)s AND o.type = 1;
