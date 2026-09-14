UPDATE agents_confighistory
   SET config = jsonb_set(
                  config::jsonb,
                  '{mcp}',
                  coalesce(config::jsonb -> 'mcp', '{}'::jsonb) || '{"enablePluginServer": true}'::jsonb,
                  true
                )::text
 WHERE active = true;
