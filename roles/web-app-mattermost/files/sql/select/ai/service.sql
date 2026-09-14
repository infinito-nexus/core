SELECT CASE
         WHEN EXISTS (SELECT 1
                        FROM jsonb_array_elements(
                               CASE WHEN jsonb_typeof(a.config::jsonb -> 'services') = 'array'
                                    THEN a.config::jsonb -> 'services'
                                    ELSE '[]'::jsonb END
                             ) AS s
                       WHERE s ->> 'id' = d.service ->> 'id'
                         AND s @> d.service)
          AND EXISTS (SELECT 1
                        FROM agents_useragents u
                       WHERE u.username = d.bot ->> 'name'
                         AND u.serviceid = d.bot ->> 'serviceID'
                         AND u.model = d.bot ->> 'model'
                         AND u.deleteat = 0
                         AND u.botuserid <> '')
          AND NOT EXISTS (SELECT 1
                            FROM jsonb_array_elements(
                                   CASE WHEN jsonb_typeof(a.config::jsonb -> 'bots') = 'array'
                                        THEN a.config::jsonb -> 'bots'
                                        ELSE '[]'::jsonb END
                                 ) AS legacy
                            JOIN agents_useragents u2
                              ON u2.username = legacy ->> 'name'
                             AND u2.deleteat = 0)
         THEN 'converged'
         ELSE 'stale'
       END
  FROM agents_confighistory a,
       (SELECT %(service)s::jsonb AS service,
               %(bot)s::jsonb AS bot) AS d
 WHERE a.active = true;
